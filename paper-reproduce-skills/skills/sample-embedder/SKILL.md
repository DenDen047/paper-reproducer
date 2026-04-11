---
name: sample-embedder
description: 再現した論文リポジトリの入出力サンプルを reports/samples/ 配下に配置し、reports/report.json の samples フィールドを生成する。/reimplement の Phase 4 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Write Grep Glob
---

# sample-embedder: 入出力サンプルの抽出と埋め込み

`/reimplement` の Phase 4 で呼び出される。Phase 3 で実際に実行された推論コマンドの入力・出力ファイルを特定し、正規化・コピーして `reports/samples/` 配下に配置する。`reports/report.html` がそれらをサムネイル表示することでユーザが結果を目視確認できるようにする。

## 対応カテゴリ

| category | 判定ヒント | 代表論文 |
|---|---|---|
| `rgb_to_rgb` | super-resolution / inpainting / style transfer / denoising / restoration / image editing / text-to-image / image-to-image | Real-ESRGAN, LaMa, ControlNet, SDXL |
| `mono_to_depth` | monocular depth / depth estimation (単眼) | Depth Anything v2, Marigold, ZoeDepth |
| `stereo_to_depth` | stereo / disparity / stereo depth | Fast-FoundationStereo, RAFT-Stereo |

**それ以外**（3D Gaussian Splatting, NeRF, point cloud, mesh, video, segmentation, detection, pose, optical flow, 等）は `category="unknown"` として空の `items` を返す。拡張は別フェーズで行う。

## 出力スキーマ

```json
{
  "samples": {
    "category": "rgb_to_rgb|mono_to_depth|stereo_to_depth|unknown",
    "items": [
      {
        "type": "image_pair|image_triple",
        "label": "string",
        "input_paths": ["samples/input/xxx.png"],
        "output_paths": ["samples/output/yyy.png"],
        "metadata": {}
      }
    ],
    "note": "string|null"
  }
}
```

**パスの記録ルール**: すべて `reports/` からの相対パス（例: `samples/input/left.png`）で記録する。これにより `reports/report.html` から同ディレクトリ内の相対参照としてそのまま機能する。

## 抽出手順

### Step 1: カテゴリ判定

**a.** Phase 3 の成功コマンドを取得:
```bash
awk -F'\t' '$3=="inference" && $5=="success" {print $4}' reports/attempts.tsv | tail -1
```
取れなければ `category="unknown"` で返す。

**b.** `reports/analysis.json` と README.md からキーワードベースで分類:
```bash
grep -iE "stereo|disparity" reports/analysis.json README.md 2>/dev/null
grep -iE "monocular depth|depth estimation|mono.?depth" reports/analysis.json README.md 2>/dev/null
grep -iE "super.?res|super resolution|inpaint|style transfer|denois|restor|image.editing|text.to.image|image.to.image" reports/analysis.json README.md 2>/dev/null
```

判定優先順位: `stereo_to_depth` → `mono_to_depth` → `rgb_to_rgb` → `unknown`
（stereo は depth の一種なので先にチェック）

### Step 2: 入出力ファイルの特定

**a.** Phase 3 の成功コマンドを解析して argparse の引数名から入出力パスを抽出:

```bash
# コマンド中の --input, --output 等を抽出
echo "$CMD" | grep -oE -- "--\w+[ =][^ ]+"
```

典型的な引数名:

| 役割 | 典型的な名前 |
|---|---|
| 単一入力 | `--input`, `--image`, `--img`, `--src`, `-i` |
| ステレオ入力 | `--left` + `--right`, `--img0` + `--img1`, `--im0` + `--im1`, `--left_img` + `--right_img` |
| 出力 | `--output`, `--out`, `--save_path`, `--save_dir`, `-o` |

**b.** コマンドから取得できない場合、Phase 3 実行直後に変化したファイルを `find` で探索:

```bash
# reports/attempts.tsv より新しい画像ファイルを検索（Phase 3 で生成されたもの）
find . -path ./reports -prune -o -path ./.pixi -prune -o \
  -type f -newer reports/attempts.tsv \
  \( -name "*.png" -o -name "*.jpg" -o -name "*.jpeg" -o -name "*.npy" -o -name "*.exr" \) \
  -print 2>/dev/null | head -10
```

**c.** デモスクリプトの argparse 定義を grep して、デフォルト値からも推定可能:

```bash
grep -nE "add_argument.*--(input|output|left|right|img|save)" {demo_script}.py
```

入出力どちらも確実でない場合は `category="unknown"`, `items=[]` を返し、`note` に理由を記載。

### Step 3: reports/samples/ への配置・正規化

**a.** ディレクトリ作成:
```bash
mkdir -p reports/samples/input reports/samples/output
```

**b.** 入力ファイルのコピー:
- そのまま `reports/samples/input/` へ `cp`（ファイル名は元のまま）
- 既存ファイル名と衝突したら数字 suffix

**c.** 出力ファイルの変換ルール:

| 元ファイル形式 | 処理 | 結果形式 |
|---|---|---|
| `.png` / `.jpg` / `.jpeg`（RGB 8bit） | そのままコピー | PNG/JPG |
| `.png`（16bit grayscale depth） | matplotlib で colormap → PNG 8bit | PNG |
| `.npy`（float32 / uint16 depth） | matplotlib で colormap → PNG | PNG |
| `.pfm`（stereo disparity 定番） | numpy で読み込み → colormap → PNG | PNG |
| `.exr` | OpenCV があれば読み込み → 正規化 → PNG | PNG |
| その他 | スキップ、`note` に記録 | — |

**d.** Colormapping 実装（matplotlib 優先、PIL フォールバック）:

```bash
pixi run python - <<'PY'
import sys, numpy as np
from pathlib import Path

src, dst = Path(sys.argv[1]), Path(sys.argv[2])

# 読み込み
if src.suffix == ".npy":
    arr = np.load(src)
elif src.suffix == ".pfm":
    # PFM reader (minimal)
    with open(src, "rb") as f:
        header = f.readline().decode().rstrip()
        dims = f.readline().decode().rstrip().split()
        w, h = int(dims[0]), int(dims[1])
        scale = float(f.readline().decode().rstrip())
        data = np.fromfile(f, np.float32 if scale < 0 else np.float32)
        arr = np.flipud(data.reshape(h, w))
else:
    from PIL import Image
    arr = np.array(Image.open(src))

# float / 16bit depth は colormap
if arr.dtype != np.uint8 or (arr.ndim == 2 and arr.dtype == np.uint8):
    valid = np.isfinite(arr) & (arr > 0) if arr.dtype.kind == "f" else np.ones_like(arr, bool)
    if valid.any():
        lo, hi = np.percentile(arr[valid].astype(np.float64), [2, 98])
    else:
        lo, hi = float(arr.min()), float(arr.max())
    norm = np.clip((arr.astype(np.float64) - lo) / (hi - lo + 1e-9), 0, 1)

    try:
        import matplotlib.cm as cm
        rgb = (cm.turbo(norm)[:, :, :3] * 255).astype(np.uint8)
    except ImportError:
        rgb = (norm * 255).astype(np.uint8)

    from PIL import Image
    Image.fromarray(rgb).save(dst)
else:
    # 既に 8bit RGB ならそのままコピー
    import shutil
    shutil.copy(src, dst)

print(f"OK {dst}")
PY
```

このスクリプトは `reports/samples/_convert.py` に書き出して `pixi run python reports/samples/_convert.py <src> <dst>` で呼ぶ方式でもよい。実行後は削除する。

### Step 4: items 構築

**category = `rgb_to_rgb`:**
```json
{
  "type": "image_pair",
  "label": "入力 → 出力",
  "input_paths": ["samples/input/input.png"],
  "output_paths": ["samples/output/result.png"],
  "metadata": {}
}
```

**category = `mono_to_depth`:**
```json
{
  "type": "image_pair",
  "label": "RGB 入力 → Depth (turbo colormap)",
  "input_paths": ["samples/input/image.png"],
  "output_paths": ["samples/output/depth.png"],
  "metadata": {"colormap": "turbo"}
}
```

**category = `stereo_to_depth`:**
```json
{
  "type": "image_triple",
  "label": "Left / Right / Disparity",
  "input_paths": ["samples/input/left.png", "samples/input/right.png"],
  "output_paths": ["samples/output/disparity.png"],
  "metadata": {"colormap": "turbo"}
}
```

## ハルシネーション対策（CRITICAL）

- **存在確認**: `input_paths` / `output_paths` は `ls reports/{path}` で実在確認してから items に追加
- **変換失敗時**: 該当 item をスキップ。全スキップで `items=[]` の場合は `category="unknown"` に降格し `note` にエラー概要
- **架空のファイルを作らない**: Phase 3 の実行結果として生成されていないファイルは記録しない。デフォルト値だけを頼りにしたパス推定は禁止
- **デモ入力の扱い**: リポジトリ同梱のサンプル入力（`assets/`, `examples/`, `demo/` 配下）を Phase 3 で使った場合はそれをコピーする。ユーザが外部から持ち込んだ入力は元パスのままコピー可

## ステータス別フォールバック

| Phase 3 status | 挙動 |
|---|---|
| `success` | 通常フロー |
| `partial` | 成功した部分の出力があれば items に含める。`note` に "部分的な成功" を記録 |
| `failed` | `category="unknown"`, `items=[]`, `note="再現失敗のためサンプルを生成できませんでした"` |

## 現バージョンの対象外（`unknown` を返すケース）

以下は別フェーズで対応する。現バージョンではすべて `category="unknown"`, `items=[]`, `note="{具体的な理由}"`:

- 3D Gaussian Splatting (`.ply`, `.splat`, `.ksplat`)
- NeRF / SDF / mesh (`.obj`, `.glb`, `.gltf`)
- Point cloud (`.pcd`, `.xyz`, 点群形式の `.ply`)
- Video (`.mp4`, `.webm`, `.avi`)
- Segmentation mask（単独でカラーマップされていない連結成分）
- Optical flow（`.flo`, 2ch 配列）
- Bounding box / keypoint（JSON 出力）
- Metrics only（ログ中の数値のみ、ファイル出力なし）

拡張時はこのセクションを各カテゴリに置き換え、`items.type` を増やす。

## 出力の保存

生成した `samples` オブジェクトは `/reimplement` Phase 4 Step 1.6 の呼び出し元に返す。呼び出し元は Step 2 で `reports/report.json` に組み込み、Step 3 で HTML にレンダリングする。

このスキルは JSON 生成 + `reports/samples/` へのファイル配置までを担当する。HTML レンダリングは行わない（責務分離）。
