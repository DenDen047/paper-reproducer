---
name: sample-embedder
description: 再現した論文リポジトリの入出力サンプルを reports/samples/ 配下に配置し、reports/report.json の samples フィールドを生成する。/reimplement の Phase 4 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Write Grep Glob
---

# sample-embedder: 入出力サンプルの抽出と埋め込み

Phase 3 の成功コマンドの入出力を `reports/samples/` に正規化コピーし、`report.json.samples` を生成する。`report.html` がサムネイル表示に使う。

## 対応カテゴリ

| category | 判定ヒント | 代表 | 出力 | item type |
|---|---|---|---|---|
| `rgb_to_rgb` | super-res / inpainting / style transfer / denoising / t2i / i2i | Real-ESRGAN, LaMa, ControlNet | PNG/JPG | `image_pair` |
| `mono_to_depth` | monocular depth | Depth Anything v2, Marigold | PNG (colormap) | `image_pair` |
| `stereo_to_depth` | stereo / disparity | RAFT-Stereo | PNG (colormap) | `image_triple` |
| `mv_to_gaussians` | 3DGS | Grendel-GS, Mip-Splatting | `.ply` / `.splat` / `.ksplat` | `gaussian_splat` |
| `images_to_pointcloud` | point cloud / DUSt3R / VGGT / MVS / SfM | DUSt3R, VGGT, COLMAP | `.ply` (xyz[rgb]) | `point_cloud` |
| `image_to_mask` | segmentation / SAM | SAM, Mask2Former | PNG (overlay) | `image_pair` |
| `image_to_bbox` | detection / YOLO / DETR | YOLOv8, Grounding DINO | PNG (boxes) | `image_pair` |
| `image_to_keypoint` | pose / keypoint | OpenPose, ViTPose | PNG (skeleton) | `image_pair` |
| `frames_to_flow` | optical flow | RAFT, GMFlow | PNG (color-wheel) | `image_triple` |
| `image_to_mesh` | image-to-3D / textured mesh | InstantMesh, TripoSR | `.glb` / `.gltf` / `.obj` | `mesh` |
| `mv_to_nerf` | NeRF / SDF | Instant-NGP, NeuS | `.mp4` (orbit) | `video` |
| `video_output` | video gen / T2V / I2V / video depth | SVD, CogVideoX | `.mp4` / `.webm` | `video` |

## 出力スキーマ

```json
{
  "samples": {
    "category": "rgb_to_rgb|...|video_output|unknown",
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

パスは全て `reports/` からの相対。

## Step 1: カテゴリ判定

Phase 3 の成功コマンド取得:
```bash
awk -F'\t' '$3=="phase3" && $6=="success" {print $4}' reports/attempts.tsv | tail -1
```

取れなければ `category="unknown"`。

取れたら `analysis.json` と README.md を「判定ヒント」列で `grep -iE` → 最大マッチのカテゴリを採用。

拡張子で確定判定（優先度順）:

| 拡張子 / 特徴 | カテゴリ |
|---|---|
| `.splat` / `.ksplat` / 3DGS ヘッダ持ち `.ply` | `mv_to_gaussians` |
| 上記外 `.ply` | `images_to_pointcloud` |
| `.glb` / `.gltf` / `.obj` | `image_to_mesh` |
| `.mp4` / `.webm` / `.avi` + NeRF キーワード | `mv_to_nerf` |
| `.mp4` / `.webm` / `.avi` + その他 | `video_output` |
| `.png` / `.jpg` + 認識系キーワード | 該当 image_to_* |
| 上記外 | grep 結果、最終的に `unknown` |

**3DGS PLY 判定** (4 属性すべて同時必須):

```bash
head -c 65536 "{file}.ply" > /tmp/_ply_head
is_3dgs=true
for k in f_dc_0 opacity scale_0 rot_0; do
    grep -q "$k" /tmp/_ply_head || { is_3dgs=false; break; }
done
rm -f /tmp/_ply_head
```

1 個だけマッチしても 3DGS と判定しない (DTU 等の独自属性 PLY や法線属性 `n_dc_*` を持つ別形式の誤検出を防ぐため)。

**PLY mesh の扱い (重要)**: 上の 3DGS 判定が偽で、かつヘッダに `element face` または `vertex_indices` を含む `.ply` は **`category=images_to_pointcloud`** (`type=point_cloud`) で扱う。`viewer-mesh` は `.glb/.gltf/.obj` のみ対応で `.ply` mesh は読み込めないため、Three.js `PLYLoader` + `THREE.Points` で点群描画にフォールバックする。

**MUST NOT**: `.ply` mesh を `category=image_to_mesh` (= `type=mesh`) に分類しない。viewer が無音で読込失敗し、ブラウザに `<a href download>` のリンクが出る。

## Step 2: 入出力ファイル特定

**a. argparse 引数から抽出**:

| 役割 | 引数名 |
|---|---|
| 単一入力 | `--input` / `--image` / `--img` / `--src` / `-i` |
| ステレオ | `--left` + `--right` / `--img0` + `--img1` |
| 出力 | `--output` / `--out` / `--save_path` / `--save_dir` / `-o` |

**b. attempts.tsv より新しいファイルを find（fallback）**:
```bash
find . -path ./reports -prune -o -path ./.pixi -prune -o \
  -type f -newer reports/attempts.tsv \
  \( -name "*.png" -o -name "*.jpg" -o -name "*.npy" -o -name "*.pfm" -o -name "*.flo" \
     -o -name "*.ply" -o -name "*.splat" -o -name "*.glb" -o -name "*.gltf" -o -name "*.obj" \
     -o -name "*.mp4" -o -name "*.webm" \) -print 2>/dev/null | head -20
```

**c. argparse default を拾う（最終 fallback）**:
```bash
grep -nE "add_argument.*--(input|output|left|right|img|save)" {demo_script}.py
```

どちらも不確実なら `category="unknown"`, `items=[]`, `note` に理由。

## Step 3: reports/samples/ 配置

```bash
mkdir -p reports/samples/input reports/samples/output
```

入力は `cp`（名前衝突時のみ数字 suffix）。出力変換:

| 元形式 | 処理 | 結果 |
|---|---|---|
| 8bit RGB PNG/JPG | そのまま | PNG/JPG |
| 16bit / float depth (PNG/NPY/PFM) | colormap (turbo) 正規化 | PNG |
| `.flo` | color-wheel | PNG |
| `.exr` | OpenCV 読込正規化 | PNG |
| `.ply` / `.splat` / `.glb` / `.gltf` / `.obj` / `.mp4` / `.webm` / `.avi` | そのまま（ブラウザ描画） | 同形式 |
| その他 | スキップして note | — |

3D/動画は圧縮しない（Three.js / `<video>` が直接読む）。`.flo` は Middlebury 形式（magic=202021.25, w/h int32, data float32 HxWx2）。

**Colormapping**（matplotlib turbo 優先、PIL fallback）:
```python
import numpy as np, sys
from pathlib import Path
src, dst = Path(sys.argv[1]), Path(sys.argv[2])
arr = np.load(src) if src.suffix==".npy" else _read_pfm(src) if src.suffix==".pfm" else np.array(__import__("PIL.Image", fromlist=["Image"]).Image.open(src))
if arr.dtype != np.uint8:
    valid = np.isfinite(arr) & (arr > 0) if arr.dtype.kind == "f" else np.ones_like(arr, bool)
    lo, hi = np.percentile(arr[valid].astype(np.float64), [2, 98]) if valid.any() else (float(arr.min()), float(arr.max()))
    norm = np.clip((arr.astype(np.float64) - lo) / (hi - lo + 1e-9), 0, 1)
    try:
        from matplotlib import cm
        rgb = (cm.turbo(norm)[:, :, :3] * 255).astype(np.uint8)
    except ImportError:
        rgb = (norm * 255).astype(np.uint8)
    from PIL import Image; Image.fromarray(rgb).save(dst)
else:
    import shutil; shutil.copy(src, dst)
```

`reports/samples/_convert.py` として書き出し、実行後に削除。

## Step 4: items 構築

`type` は対応表「item type」列に従う。

| カテゴリ | label 雛形 | input | output | metadata |
|---|---|---|---|---|
| `rgb_to_rgb` | 入力 → 出力 | 1 | 1 | `{}` |
| `mono_to_depth` | RGB → Depth (turbo) | 1 | 1 | `{"colormap": "turbo"}` |
| `stereo_to_depth` | Left / Right / Disparity | 2 | 1 | `{"colormap": "turbo"}` |
| `mv_to_gaussians` | 再構成された 3D Gaussians | [] | 1 | `{"format", "gaussian_count", "coord_convention"}` (PLY `element vertex N`) |
| `images_to_pointcloud` | 再構成された点群 | [] | 1 | `{"format", "point_count", "has_color", "coord_convention"}` (`property uchar red` 有無) |
| `image_to_mask` | 入力 → セグメンテーションマスク | 1 | 1 | `{"task": "segmentation"}` |
| `image_to_bbox` | 入力 → 検出結果 (bounding boxes) | 1 | 1 | `{"task": "detection"}` |
| `image_to_keypoint` | 入力 → 姿勢推定 (keypoints) | 1 | 1 | `{"task": "pose"}` |
| `frames_to_flow` | Frame 1 / Frame 2 / Flow | 2 | 1 | `{"visualization": "color_wheel"}` |
| `image_to_mesh` | 再構成されたメッシュ | 1 | 1 | `{"format", "has_texture", "coord_convention"}` |
| `mv_to_nerf` | 再構成結果 (orbit rendering) | [] | 1 | `{"format", "note": "pre-rendered orbit"}` |
| `video_output` | 生成動画 | [] | 1 | `{"format": "mp4"}` |

認識系（mask / bbox / keypoint）は pre-visualized overlay RGB がある場合のみ採用。座標/raw mask のみなら `unknown` + note。`mv_to_nerf` は orbit 動画なしなら `unknown`。

## Step 4.5: 座標系規約の埋め込み（3D types のみ）

`mv_to_gaussians` / `images_to_pointcloud` / `image_to_mesh` の `metadata.coord_convention` に **その 3D 出力の座標系規約** を入れる。Three.js viewer がこの値を見て X 軸 180° 回転を適用するか決める。誤判定で **上下逆さま / 鏡像表示** になる古典バグを防ぐため。

優先順位:

1. `analysis.json.coord_convention.world` を一次情報として採用
2. 上記が `unknown` で `mv_to_gaussians` の場合: **`opencv` に格上げ**（3DGS PLY 形式は事実上 OpenCV ヘリテージ Inria/Mip-Splatting/Grendel-GS）。`note` に `"coord inferred from 3DGS heritage"` を追記
3. 上記が `unknown` で `images_to_pointcloud` の場合: 出力 `.ply` 先頭で Z 分布をチェック（`pixi run python -c "..."` 等で `pts[:,2].min(), pts[:,2].max()` を取得）。両方正なら `opencv`、両方負なら `opengl`、混在なら `unknown` のまま
4. それ以外は `unknown` を保持し、`samples.note` に `"coord_convention=unknown for 3D output; viewer may show flipped — verify manually"` を 1 行追記

値は `"opencv" | "opengl" | "z_up" | "unknown"` のいずれか。

### Z 分布による判別レシピ（参考）

```python
# 軽量 PLY 読み: header の "format ascii" / "format binary_little_endian" を検出
# vertex の x/y/z 列を読む。先頭 N 点 (例 1000) で十分
import struct
def quick_z_range(path, n_sample=1000):
    with open(path, "rb") as f:
        # 先頭 4KB を読んで header を解析
        head = f.read(4096).decode("ascii", errors="ignore")
        # 'element vertex N' / 'property * x' / 'property * y' / 'property * z' を抽出
        # 'end_header' 以降がデータ。format ascii or binary を分岐
        ...
    return zmin, zmax
```

実装は agent が必要に応じて生成。確信を持てなければ `unknown` のまま。

## 必須チェック

- `input_paths` / `output_paths` は `ls reports/{path}` で実在確認後に追加
- 変換失敗 item はスキップ、全滅なら `category="unknown"` + note
- 実在しないファイルは記録しない
- Phase 3 で使った同梱サンプル（`assets/`, `examples/`, `demo/`）は `reports/samples/input/` にコピー
- **UV atlas / texture map / loss curve / debug visualization は独立 item にしない**。関連する 3D 成果物の `metadata` に記録する (例: textured mesh の `.png` テクスチャ → `metadata.texture_atlas: "samples/output/atlas.png"`、学習可視化 → `metadata.note`)。「画像で、入力画像と並べられる」だけで `image_pair` に分類しない (= 入力と意味的に対比できる出力かを確認する)。
- **`reports/samples/` 配下に symlink を置かない**。`git archive HEAD` は symlink を含めるが、展開先で実体が無ければ dangling になる。`cp -L` で実体コピーする。

## status 別挙動

| Phase 3 status | 挙動 |
|---|---|
| `success` | 通常フロー |
| `partial` | 成功分のみ items、note に「部分的な成功」 |
| `failed` | `unknown`, `items=[]`, note に理由 |

## unknown で返すケース

- NeRF/SDF の raw weights (`.pth`/`.ckpt`) + orbit video なし
- 非 PLY 点群 (`.pcd` / `.xyz`)
- 可視化されていない raw mask / bbox / keypoint JSON のみ
- Metrics only（ファイル出力なし）

## 出力言語

`samples.items[].label` と `samples.note` は環境変数 `$REPORT_LANG` (デフォルト `ja`、`en` も可) に従う。Step 4 表中の label 雛形は `ja` 想定。`en` 時の対応:

| ja | en |
|---|---|
| 入力 → 出力 | Input → Output |
| RGB → Depth (turbo) | RGB → Depth (turbo) |
| Left / Right / Disparity | Left / Right / Disparity |
| 再構成された 3D Gaussians | Reconstructed 3D Gaussians |
| 再構成された点群 | Reconstructed point cloud |
| 入力 → セグメンテーションマスク | Input → Segmentation mask |
| 入力 → 検出結果 (bounding boxes) | Input → Detections (bounding boxes) |
| 入力 → 姿勢推定 (keypoints) | Input → Pose (keypoints) |
| Frame 1 / Frame 2 / Flow | Frame 1 / Frame 2 / Flow |
| 再構成されたメッシュ | Reconstructed mesh |
| 再構成結果 (orbit rendering) | Reconstruction (orbit rendering) |
| 生成動画 | Generated video |

`note` の固定句（例「部分的な成功」「coord inferred from 3DGS heritage」）も `$REPORT_LANG` に従う。固有名詞 (3DGS, PLY, OpenCV 等) は翻訳しない。

## 契約

JSON 生成と `reports/samples/` 配置まで担当。HTML レンダリングは行わない（責務分離）。返した samples オブジェクトを Phase 4 Step 1.6 の呼び出し元が `report.json` に組み込む。
