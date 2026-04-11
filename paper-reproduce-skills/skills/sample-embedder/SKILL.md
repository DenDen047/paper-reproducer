---
name: sample-embedder
description: 再現した論文リポジトリの入出力サンプルを reports/samples/ 配下に配置し、reports/report.json の samples フィールドを生成する。/reimplement の Phase 4 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Write Grep Glob
---

# sample-embedder: 入出力サンプルの抽出と埋め込み

`/reimplement` の Phase 4 で呼び出される。Phase 3 で実際に実行された推論コマンドの入力・出力ファイルを特定し、正規化・コピーして `reports/samples/` 配下に配置する。`reports/report.html` がそれらをサムネイル表示することでユーザが結果を目視確認できるようにする。

## 対応カテゴリ

| category | 判定ヒント | 代表論文 | 出力形式 | item type |
|---|---|---|---|---|
| `rgb_to_rgb` | super-resolution / inpainting / style transfer / denoising / restoration / image editing / text-to-image / image-to-image | Real-ESRGAN, LaMa, ControlNet, SDXL | PNG/JPG | `image_pair` |
| `mono_to_depth` | monocular depth / depth estimation (単眼) | Depth Anything v2, Marigold, ZoeDepth | PNG (colormapped) | `image_pair` |
| `stereo_to_depth` | stereo / disparity / stereo depth | Fast-FoundationStereo, RAFT-Stereo | PNG (colormapped) | `image_triple` |
| `mv_to_gaussians` | 3D Gaussian Splatting / 3DGS | Grendel-GS, 3DGS, Mip-Splatting | `.ply` / `.splat` / `.ksplat` | `gaussian_splat` |
| `images_to_pointcloud` | point cloud reconstruction / DUSt3R / VGGT / MVS / SfM | DUSt3R, VGGT, MVSNet, COLMAP | `.ply` (xyz[rgb]) | `point_cloud` |
| `image_to_mask` | segmentation / SAM / mask / semantic seg | SAM, SAM 2, Mask2Former, OneFormer | PNG (visualized overlay) | `image_pair` |
| `image_to_bbox` | object detection / YOLO / DETR / bounding box | YOLOv8, DETR, Grounding DINO | PNG (with boxes drawn) | `image_pair` |
| `image_to_keypoint` | pose / keypoint / skeleton / OpenPose | OpenPose, ViTPose, MediaPipe | PNG (with skeleton) | `image_pair` |
| `frames_to_flow` | optical flow / RAFT | RAFT, SEA-RAFT, GMFlow | PNG (color-wheel flow) | `image_triple` |
| `image_to_mesh` | image-to-3D / mesh / textured mesh | InstantMesh, TripoSR, LGM, DreamFusion | `.glb` / `.gltf` / `.obj` | `mesh` |
| `mv_to_nerf` | NeRF / neural radiance field / SDF reconstruction | Instant-NGP, Mip-NeRF 360, NeuS | `.mp4` (pre-rendered orbit) | `video` |
| `video_output` | video generation / T2V / I2V / video depth / video segmentation / action recognition | SVD, CogVideoX, Open-Sora, SlowFast | `.mp4` / `.webm` | `video` |

**対象外** — 以下は `category="unknown"` で返す:
- NeRF/SDF の raw weights (`.pth`, `.ckpt`) — pre-rendered orbit video が無ければ可視化不能
- 純 JSON / bbox 座標のみ（visualized overlay が生成されていない場合）
- Metrics only（数値のログのみ）

## 出力スキーマ

```json
{
  "samples": {
    "category": "rgb_to_rgb|mono_to_depth|stereo_to_depth|mv_to_gaussians|images_to_pointcloud|image_to_mask|image_to_bbox|image_to_keypoint|frames_to_flow|image_to_mesh|mv_to_nerf|video_output|unknown",
    "items": [
      {
        "type": "image_pair|image_triple|gaussian_splat|point_cloud|mesh|video",
        "label": "string",
        "input_paths": ["samples/input/xxx.png"],
        "output_paths": ["samples/output/yyy.ext"],
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
# 3D 系
grep -iE "gaussian splat|3dgs|gaussian-splatting" reports/analysis.json README.md 2>/dev/null
grep -iE "point cloud|pointcloud|dust3r|vggt|mvs|colmap|sfm" reports/analysis.json README.md 2>/dev/null
grep -iE "nerf|neural radiance|radiance field|instant.?ngp|neus|sdf" reports/analysis.json README.md 2>/dev/null
grep -iE "image.to.3d|text.to.3d|mesh|\\.glb|\\.gltf|triposr|instantmesh" reports/analysis.json README.md 2>/dev/null
# 2D カテゴリ
grep -iE "stereo|disparity" reports/analysis.json README.md 2>/dev/null
grep -iE "monocular depth|depth estimation|mono.?depth" reports/analysis.json README.md 2>/dev/null
grep -iE "super.?res|super resolution|inpaint|style transfer|denois|restor|image.editing|text.to.image|image.to.image" reports/analysis.json README.md 2>/dev/null
# 認識系
grep -iE "segment|\\bsam\\b|mask2former|oneformer|semantic seg|instance seg|panoptic" reports/analysis.json README.md 2>/dev/null
grep -iE "object detect|yolo|\\bdetr\\b|bounding box|grounding.?dino" reports/analysis.json README.md 2>/dev/null
grep -iE "pose estimation|keypoint|skeleton|openpose|\\bvitpose\\b|\\bhrnet\\b" reports/analysis.json README.md 2>/dev/null
grep -iE "optical flow|\\braft\\b|flowformer|gmflow" reports/analysis.json README.md 2>/dev/null
# 動画系
grep -iE "video generation|text.to.video|image.to.video|t2v|\\bi2v\\b|video diffusion|video depth|video segment|action recognition|video classif" reports/analysis.json README.md 2>/dev/null
```

**c.** 出力ファイル拡張子からも推定:

| 拡張子 | 判定 |
|---|---|
| `.splat` / `.ksplat` | `mv_to_gaussians` 確定 |
| `.ply` (header に `f_dc_0` / `scale_0` / `rot_0` / `opacity` あり) | `mv_to_gaussians` |
| `.ply` (上記プロパティ無し) | `images_to_pointcloud` |
| `.glb` / `.gltf` / `.obj` | `image_to_mesh` |
| `.mp4` / `.webm` / `.avi` + README に NeRF 系キーワード | `mv_to_nerf` |
| `.mp4` / `.webm` / `.avi` + 上記以外 | `video_output` |
| `.png` / `.jpg` + mask/seg キーワード | `image_to_mask` |
| `.png` / `.jpg` + detect/yolo/bbox キーワード | `image_to_bbox` |
| `.png` / `.jpg` + pose/keypoint キーワード | `image_to_keypoint` |
| `.png` / `.jpg` / `.flo` + optical flow キーワード | `frames_to_flow` |
| 上記以外の画像 | `stereo_to_depth` → `mono_to_depth` → `rgb_to_rgb` → `unknown` |

PLY header 判定:
```bash
# 3DGS 判定: f_dc_0 / scale_0 / rot_0 / opacity プロパティがあれば 3DGS
head -c 4096 {file}.ply | grep -qE "property float (f_dc_0|scale_0|rot_0|opacity)" && echo "gsplat" || echo "pointcloud"
```

**判定優先順位**（拡張子 > キーワード）:
1. `.splat` / `.ksplat` or 3DGS 形式 `.ply` → `mv_to_gaussians`
2. 点群形式 `.ply` → `images_to_pointcloud`
3. `.glb` / `.gltf` / `.obj` → `image_to_mesh`
4. `.mp4` / `.webm` / `.avi` → キーワードで `mv_to_nerf` or `video_output`
5. 画像 + 認識系キーワード → `image_to_mask` / `image_to_bbox` / `image_to_keypoint` / `frames_to_flow`
6. `stereo_to_depth` → `mono_to_depth` → `rgb_to_rgb` → `unknown`

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
# reports/attempts.tsv より新しい成果物ファイルを検索（Phase 3 で生成されたもの）
find . -path ./reports -prune -o -path ./.pixi -prune -o \
  -type f -newer reports/attempts.tsv \
  \( -name "*.png" -o -name "*.jpg" -o -name "*.jpeg" \
     -o -name "*.npy" -o -name "*.pfm" -o -name "*.exr" -o -name "*.flo" \
     -o -name "*.ply" -o -name "*.splat" -o -name "*.ksplat" \
     -o -name "*.glb" -o -name "*.gltf" -o -name "*.obj" \
     -o -name "*.mp4" -o -name "*.webm" -o -name "*.avi" \) \
  -print 2>/dev/null | head -20
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
| `.flo`（optical flow 2ch） | Middlebury flow reader → color wheel PNG | PNG |
| `.exr` | OpenCV があれば読み込み → 正規化 → PNG | PNG |
| `.ply`（3DGS, 点群どちらも） | そのままコピー | .ply |
| `.splat` / `.ksplat`（3DGS 圧縮形式） | そのままコピー | .splat/.ksplat |
| `.glb` / `.gltf` / `.obj`（mesh） | そのままコピー | 同形式 |
| `.mp4` / `.webm` / `.avi`（video） | そのままコピー（H.264/VP9 前提） | 同形式 |
| その他 | スキップ、`note` に記録 | — |

**3D / video ファイルは変換しない。** ブラウザ側で Three.js (`PLYLoader` / `GLTFLoader` / `OBJLoader`) や `<video>` タグが直接読む。`.ply` / `.glb` / `.mp4` のサイズが大きい場合でも圧縮は行わない。

**`.flo` の読み取り（Middlebury 形式）:**
```python
def read_flo(path):
    import numpy as np
    with open(path, "rb") as f:
        magic = np.fromfile(f, np.float32, 1)
        if magic != 202021.25:
            raise ValueError("invalid .flo file")
        w = int(np.fromfile(f, np.int32, 1))
        h = int(np.fromfile(f, np.int32, 1))
        data = np.fromfile(f, np.float32, 2 * w * h).reshape(h, w, 2)
    return data  # (H, W, 2)
```

`flow → color wheel` 変換は `cv2.optflow` or Python 実装の HSV → RGB で実施。

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

**category = `mv_to_gaussians`:**
```json
{
  "type": "gaussian_splat",
  "label": "再構成された 3D Gaussian Splats",
  "input_paths": [],
  "output_paths": ["samples/output/scene.ply"],
  "metadata": {
    "format": "ply",
    "gaussian_count": 1250000
  }
}
```

`input_paths` は空配列で良い。`gaussian_count` は PLY header の `element vertex N` から取得:
```bash
head -c 4096 {file}.ply | grep -oE "element vertex [0-9]+" | awk '{print $3}'
```

**category = `images_to_pointcloud`:**
```json
{
  "type": "point_cloud",
  "label": "再構成された点群",
  "input_paths": [],
  "output_paths": ["samples/output/cloud.ply"],
  "metadata": {
    "format": "ply",
    "point_count": 50000,
    "has_color": true
  }
}
```

`has_color` は PLY header に `property uchar red/green/blue` があれば `true`:
```bash
head -c 4096 {file}.ply | grep -q "property uchar red" && echo true || echo false
```

**category = `image_to_mask` / `image_to_bbox` / `image_to_keypoint`:**

いずれも「入力 RGB + 可視化済み出力 RGB」の 2 枚ペアなので `image_pair` を使う:
```json
{
  "type": "image_pair",
  "label": "入力 → マスク可視化" ,
  "input_paths": ["samples/input/image.png"],
  "output_paths": ["samples/output/mask_overlay.png"],
  "metadata": {"task": "segmentation"}
}
```

ラベル例:
- `image_to_mask`: "入力 → セグメンテーションマスク"
- `image_to_bbox`: "入力 → 検出結果 (bounding boxes)"
- `image_to_keypoint`: "入力 → 姿勢推定 (keypoints)"

**重要**: 出力が pre-visualized な RGB 画像の場合にのみこれらのカテゴリを採用する。出力が純粋なマスク PNG / bbox JSON / keypoint JSON のみで可視化されていない場合は `category="unknown"` にし、`note` に「出力は座標/raw mask のみで pre-rendered の可視化なし」を記載する。

**category = `frames_to_flow`:**
```json
{
  "type": "image_triple",
  "label": "Frame 1 / Frame 2 / Optical Flow",
  "input_paths": ["samples/input/frame1.png", "samples/input/frame2.png"],
  "output_paths": ["samples/output/flow.png"],
  "metadata": {"visualization": "color_wheel"}
}
```

**category = `image_to_mesh`:**
```json
{
  "type": "mesh",
  "label": "再構成されたメッシュ",
  "input_paths": ["samples/input/image.png"],
  "output_paths": ["samples/output/mesh.glb"],
  "metadata": {
    "format": "glb",
    "has_texture": true
  }
}
```

`format` は `glb` / `gltf` / `obj` のいずれか（実ファイルの拡張子と一致）。

**category = `mv_to_nerf`:**
```json
{
  "type": "video",
  "label": "再構成結果 (orbit rendering)",
  "input_paths": [],
  "output_paths": ["samples/output/orbit.mp4"],
  "metadata": {
    "format": "mp4",
    "note": "pre-rendered orbit video"
  }
}
```

NeRF 本体の weights はブラウザでは再生できないため、訓練後の orbit レンダリングを pre-computed video として表示する。Phase 3 で orbit rendering が実行されていなければ `category="unknown"` にフォールバック。

**category = `video_output`:**
```json
{
  "type": "video",
  "label": "生成動画",
  "input_paths": [],
  "output_paths": ["samples/output/result.mp4"],
  "metadata": {
    "format": "mp4"
  }
}
```

T2V / I2V / video depth / video segmentation / action recognition いずれも同じ `video` item type で表現する。必要に応じて `label` で区別する。

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

以下は `category="unknown"`, `items=[]`, `note="{具体的な理由}"` で返す:

- NeRF / SDF の raw weights（`.pth` / `.ckpt`）で orbit rendering が無い場合
- Point cloud の非 PLY 形式（`.pcd` / `.xyz`）
- 純粋な mask PNG / bbox JSON / keypoint JSON のみで pre-visualized 出力が無い場合
- Metrics only（ログ中の数値のみ、ファイル出力なし）
## 出力の保存

生成した `samples` オブジェクトは `/reimplement` Phase 4 Step 1.6 の呼び出し元に返す。呼び出し元は Step 2 で `reports/report.json` に組み込み、Step 3 で HTML にレンダリングする。

このスキルは JSON 生成 + `reports/samples/` へのファイル配置までを担当する。HTML レンダリングは行わない（責務分離）。
