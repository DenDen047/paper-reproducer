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
awk -F'\t' '$3=="inference" && $5=="success" {print $4}' reports/attempts.tsv | tail -1
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

3DGS PLY 判定: `head -c 4096 {file}.ply | grep -qE "property float (f_dc_0|scale_0|rot_0|opacity)"`。

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
| `mv_to_gaussians` | 再構成された 3D Gaussians | [] | 1 | `{"format", "gaussian_count"}` (PLY `element vertex N`) |
| `images_to_pointcloud` | 再構成された点群 | [] | 1 | `{"format", "point_count", "has_color"}` (`property uchar red` 有無) |
| `image_to_mask` | 入力 → セグメンテーションマスク | 1 | 1 | `{"task": "segmentation"}` |
| `image_to_bbox` | 入力 → 検出結果 (bounding boxes) | 1 | 1 | `{"task": "detection"}` |
| `image_to_keypoint` | 入力 → 姿勢推定 (keypoints) | 1 | 1 | `{"task": "pose"}` |
| `frames_to_flow` | Frame 1 / Frame 2 / Flow | 2 | 1 | `{"visualization": "color_wheel"}` |
| `image_to_mesh` | 再構成されたメッシュ | 1 | 1 | `{"format", "has_texture"}` |
| `mv_to_nerf` | 再構成結果 (orbit rendering) | [] | 1 | `{"format", "note": "pre-rendered orbit"}` |
| `video_output` | 生成動画 | [] | 1 | `{"format": "mp4"}` |

認識系（mask / bbox / keypoint）は pre-visualized overlay RGB がある場合のみ採用。座標/raw mask のみなら `unknown` + note。`mv_to_nerf` は orbit 動画なしなら `unknown`。

## 必須チェック

- `input_paths` / `output_paths` は `ls reports/{path}` で実在確認後に追加
- 変換失敗 item はスキップ、全滅なら `category="unknown"` + note
- 実在しないファイルは記録しない
- Phase 3 で使った同梱サンプル（`assets/`, `examples/`, `demo/`）は `reports/samples/input/` にコピー

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

## 契約

JSON 生成と `reports/samples/` 配置まで担当。HTML レンダリングは行わない（責務分離）。返した samples オブジェクトを Phase 4 Step 1.6 の呼び出し元が `report.json` に組み込む。
