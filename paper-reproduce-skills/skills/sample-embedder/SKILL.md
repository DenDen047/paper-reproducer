---
name: sample-embedder
description: 再現した論文リポジトリの入出力サンプルを reports/samples/ 配下に配置し、reports/report.json の samples フィールドを生成する。/reimplement の Phase 4 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Write Grep Glob
---

# sample-embedder: 入出力サンプルの抽出と埋め込み

Phase 3 で実行された推論コマンドの入出力ファイルを `reports/samples/` に正規化コピーし、`report.json.samples` を生成する。`report.html` がサムネイル表示に利用する。

## 対応カテゴリ

| category | 判定ヒント | 代表論文 | 出力形式 | item type |
|---|---|---|---|---|
| `rgb_to_rgb` | super-resolution / inpainting / style transfer / denoising / text-to-image / image-to-image | Real-ESRGAN, LaMa, ControlNet, SDXL | PNG/JPG | `image_pair` |
| `mono_to_depth` | monocular depth (単眼) | Depth Anything v2, Marigold, ZoeDepth | PNG (colormapped) | `image_pair` |
| `stereo_to_depth` | stereo / disparity | Fast-FoundationStereo, RAFT-Stereo | PNG (colormapped) | `image_triple` |
| `mv_to_gaussians` | 3D Gaussian Splatting / 3DGS | Grendel-GS, 3DGS, Mip-Splatting | `.ply` / `.splat` / `.ksplat` | `gaussian_splat` |
| `images_to_pointcloud` | point cloud / DUSt3R / VGGT / MVS / SfM | DUSt3R, VGGT, MVSNet, COLMAP | `.ply` (xyz[rgb]) | `point_cloud` |
| `image_to_mask` | segmentation / SAM / semantic seg | SAM, SAM 2, Mask2Former | PNG (overlay) | `image_pair` |
| `image_to_bbox` | object detection / YOLO / DETR | YOLOv8, DETR, Grounding DINO | PNG (boxes drawn) | `image_pair` |
| `image_to_keypoint` | pose / keypoint / OpenPose | OpenPose, ViTPose, MediaPipe | PNG (skeleton) | `image_pair` |
| `frames_to_flow` | optical flow | RAFT, SEA-RAFT, GMFlow | PNG (color-wheel) | `image_triple` |
| `image_to_mesh` | image-to-3D / textured mesh | InstantMesh, TripoSR, LGM | `.glb` / `.gltf` / `.obj` | `mesh` |
| `mv_to_nerf` | NeRF / SDF reconstruction | Instant-NGP, Mip-NeRF 360, NeuS | `.mp4` (pre-rendered orbit) | `video` |
| `video_output` | video generation / T2V / I2V / video depth / video seg | SVD, CogVideoX, Open-Sora | `.mp4` / `.webm` | `video` |

## 出力スキーマ

```json
{
  "samples": {
    "category": "rgb_to_rgb|mono_to_depth|...|video_output|unknown",
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

パスはすべて `reports/` からの相対。`report.html` が同階層で相対参照する。

## 抽出手順

### Step 1: カテゴリ判定

a. Phase 3 の成功コマンドを取得:
```bash
awk -F'\t' '$3=="inference" && $5=="success" {print $4}' reports/attempts.tsv | tail -1
```
取れなければ `category="unknown"` で返す。

b. `analysis.json` と README.md を上表「判定ヒント」のキーワードで `grep -iE` して最大マッチのカテゴリを選ぶ。

c. 拡張子からの確定判定 (優先度順):

| 拡張子 / 特徴 | カテゴリ |
|---|---|
| `.splat` / `.ksplat` / `.ply` with `f_dc_0\|scale_0\|rot_0\|opacity` header | `mv_to_gaussians` |
| 上記以外の `.ply` | `images_to_pointcloud` |
| `.glb` / `.gltf` / `.obj` | `image_to_mesh` |
| `.mp4` / `.webm` / `.avi` + NeRF 系キーワード | `mv_to_nerf` |
| `.mp4` / `.webm` / `.avi` + 他 | `video_output` |
| `.png` / `.jpg` + 認識系キーワード | 該当の image_to_* |
| 上記外 | b の結果にフォールバック、最終的に `unknown` |

PLY header 判定: `head -c 4096 {file}.ply | grep -qE "property float (f_dc_0|scale_0|rot_0|opacity)"` で 3DGS かを判定。

### Step 2: 入出力ファイルの特定

a. 成功コマンドから argparse の引数を抽出。典型名:

| 役割 | 引数名 |
|---|---|
| 単一入力 | `--input` / `--image` / `--img` / `--src` / `-i` |
| ステレオ | `--left` + `--right` / `--img0` + `--img1` |
| 出力 | `--output` / `--out` / `--save_path` / `--save_dir` / `-o` |

b. 取れなければ attempts.tsv より新しいファイルを find:
```bash
find . -path ./reports -prune -o -path ./.pixi -prune -o \
  -type f -newer reports/attempts.tsv \
  \( -name "*.png" -o -name "*.jpg" -o -name "*.npy" -o -name "*.pfm" -o -name "*.flo" \
     -o -name "*.ply" -o -name "*.splat" -o -name "*.glb" -o -name "*.gltf" -o -name "*.obj" \
     -o -name "*.mp4" -o -name "*.webm" \) -print 2>/dev/null | head -20
```

c. デモスクリプトの argparse から default 値を拾う fallback:
```bash
grep -nE "add_argument.*--(input|output|left|right|img|save)" {demo_script}.py
```

入出力どちらも不確実なら `category="unknown"`, `items=[]`, note に理由を記載。

### Step 3: reports/samples/ への配置

```bash
mkdir -p reports/samples/input reports/samples/output
```

入力は `cp` (名前衝突時のみ数字 suffix)。出力の変換ルール:

| 元形式 | 処理 | 結果 |
|---|---|---|
| 8bit RGB PNG/JPG | そのまま | PNG/JPG |
| 16bit / float depth (PNG/NPY/PFM) | colormap (turbo) 正規化 | PNG |
| `.flo` (optical flow) | color-wheel 変換 | PNG |
| `.exr` | OpenCV で読み込み正規化 | PNG |
| `.ply` / `.splat` / `.glb` / `.gltf` / `.obj` / `.mp4` / `.webm` / `.avi` | そのまま (ブラウザ側で描画) | 同形式 |
| 他 | スキップし note に記録 | — |

3D/動画ファイルは圧縮しない (Three.js/`<video>` が直接読む)。`.flo` は Middlebury 形式 (magic=202021.25, w/h int32, data float32 HxWx2)。

**Colormapping (matplotlib turbo 優先、PIL フォールバック)**:
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
実装用に `reports/samples/_convert.py` として書き出し、実行後に削除。

### Step 4: items 構築

`type` は対応カテゴリ表の「item type」列に従う。共通パターンのみ示す:

| カテゴリ | label の雛形 | input_paths | output_paths | metadata の追加 |
|---|---|---|---|---|
| `rgb_to_rgb` | "入力 → 出力" | 入力 1 | 出力 1 | `{}` |
| `mono_to_depth` | "RGB → Depth (turbo)" | 入力 1 | 出力 1 | `{"colormap": "turbo"}` |
| `stereo_to_depth` | "Left / Right / Disparity" | 入力 2 | 出力 1 | `{"colormap": "turbo"}` |
| `mv_to_gaussians` | "再構成された 3D Gaussians" | [] | `.ply`/`.splat` 1 | `{"format", "gaussian_count"}` (PLY header の `element vertex N`) |
| `images_to_pointcloud` | "再構成された点群" | [] | `.ply` 1 | `{"format", "point_count", "has_color"}` (`property uchar red` 有無) |
| `image_to_mask` | "入力 → セグメンテーションマスク" | 入力 1 | overlay 1 | `{"task": "segmentation"}` |
| `image_to_bbox` | "入力 → 検出結果 (bounding boxes)" | 入力 1 | overlay 1 | `{"task": "detection"}` |
| `image_to_keypoint` | "入力 → 姿勢推定 (keypoints)" | 入力 1 | overlay 1 | `{"task": "pose"}` |
| `frames_to_flow` | "Frame 1 / Frame 2 / Flow" | 入力 2 | 出力 1 | `{"visualization": "color_wheel"}` |
| `image_to_mesh` | "再構成されたメッシュ" | 入力 1 | `.glb`/`.gltf`/`.obj` 1 | `{"format", "has_texture"}` |
| `mv_to_nerf` | "再構成結果 (orbit rendering)" | [] | `.mp4` 1 | `{"format", "note": "pre-rendered orbit"}` |
| `video_output` | "生成動画" | [] | `.mp4` 1 | `{"format": "mp4"}` |

認識系 (`image_to_mask` / `image_to_bbox` / `image_to_keypoint`) は pre-visualized な overlay RGB がある場合のみ採用。座標/raw mask のみなら `unknown` + note に明記。`mv_to_nerf` は orbit 動画が生成されていなければ `unknown`。

## 必須チェック

- `input_paths` / `output_paths` は `ls reports/{path}` で実在確認後に追加
- 変換失敗 item はスキップ、全滅なら `category="unknown"` + note
- 推定パスのみで実在しないファイルは記録しない
- Phase 3 で使った同梱サンプル (`assets/`, `examples/`, `demo/`) は reports/samples/input/ にコピー

## status 別フォールバック

| Phase 3 status | 挙動 |
|---|---|
| `success` | 通常フロー |
| `partial` | 成功分だけ items に含める、note に "部分的な成功" |
| `failed` | `unknown`, `items=[]`, note に理由 |

## unknown で返すケース

- NeRF/SDF の raw weights (`.pth`/`.ckpt`) + orbit video 無し
- Point cloud の非 PLY 形式 (`.pcd` / `.xyz`)
- 可視化されていない raw mask / bbox / keypoint JSON のみ
- Metrics only (ファイル出力なし)

## 呼び出し元との契約

JSON 生成と `reports/samples/` 配下のファイル配置までを担当。HTML レンダリングは行わない (責務分離)。返した samples オブジェクトを Phase 4 Step 1.6 の呼び出し元が `report.json` に組み込む。
