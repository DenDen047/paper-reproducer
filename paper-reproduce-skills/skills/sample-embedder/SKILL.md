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

## Step 2.5: mesh format 正規化 (glb 強制)

`type=mesh` の sample の input が `.ply` / `.stl` / `.off` 等の場合、Three.js の `GLTFLoader` / `OBJLoader` は読めない (RENDERING.md で対応形式は `.glb` / `.gltf` / `.obj` のみと明記)。**samples/output/ に置く前に `.glb` (単一バイナリ) に変換する**。

> `.ply` で `element face` を含む mesh は `category=images_to_pointcloud` で点群表示する別ルート (Step 1) があるが、そちらは「mesh 表示を諦めて点群描画にフォールバック」する保険。本セクションは「mesh として表示したい」ケースの正規化。

### 変換 fallback chain (順に試行、最初に成功した経路を採用)

1. **open3d**: `o3d.io.read_triangle_mesh` → `simplify_quadric_decimation(target=200_000)` → `trimesh.load(...).export('.glb')`
   - faces 0 件 / 多様体エラー / texture 参照解決失敗のいずれかで失敗
2. **trimesh**: `trimesh.load(<src>, force='mesh')` → `export('.glb')` (vertex_colors を保持、texture は破棄)
3. **pymeshlab**: `MeshSet().load_new_mesh(<src>)` → `meshing_remove_unreferenced_vertices` → `save_current_mesh(<dst.glb>)` (non-manifold cleanup)
4. **最終 fallback**: `type=mesh` を諦めて `type=point_cloud` に降格
   - mesh.vertices だけ抽出し `.ply (point_cloud)` として埋め込む
   - `note` フィールドに「mesh 変換不可のため点群表示。フル mesh は <output_dir>/<file>」を追記

### glTF 出力ルール

- 必ず `.glb` (単一バイナリ) に書き出す
- `.gltf` + 外部 texture 参照は Three.js の CORS / 相対パス解決でハマるため使わない

### サイズ制約 (hard limit)

| type | hard limit | 超過時 |
|---|---|---|
| `glb` mesh | 5 MB | `simplify_quadric_decimation` の target を半減して再変換、それでも超えるなら fallback chain の次へ |
| `ply` gaussian_splat / point_cloud | 15 MB | Step 4.6 (Gaussian PLY subsample) で対処 |

faces 数や point 数を上限化するのではなく **byte 上限のみ** で判定する (Gaussian PLY は SH 係数 / scale / rotation / opacity を含み点数と byte が線形でないため)。

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
| `.ply` (point_cloud / gaussian_splat) / `.splat` / `.glb` / `.gltf` / `.obj` / `.mp4` / `.webm` / `.avi` | そのまま（ブラウザ描画） | 同形式 |
| `.ply` (mesh, `element face` あり) / `.stl` / `.off` で `type=mesh` | Step 2.5 の fallback chain で `.glb` に変換 | `.glb` |
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

## Step 4.5.5: 3D Gaussian の主出力を動画化 (`mv_to_gaussians` のみ)

Three.js の `gaussian-splats-3d` viewer は標準 3DGS スキーマ (`f_dc_*`, `scale_0..2`, `rot_0..3`, `opacity` 等) を前提とする。論文派生 (2DGS / Scaffold-GS / GoF / GeoGS / Mip-Splatting 等) はスキーマを拡張・改変するため、**ブラウザでのレンダリングが失敗または不正表示**になる。確実な可視化のため、`mv_to_gaussians` の **主出力を動画 (.mp4) に切り替える**。

### Step 4.5.5-a: PLY 互換性検証

`scripts/render_gaussian_video.py --check-ply $PLY` が JSON を返す:

```json
{"is_standard": true|false, "missing": [...], "extra": [...], "reason": "missing scale_2 (likely 2DGS / planar gaussian)"}
```

`required = {x,y,z, f_dc_0..2, scale_0..2, rot_0..3, opacity}` の部分集合を満たさなければ non_standard。

### Step 4.5.5-b: 動画レンダリング (順に試行、最初に成功した経路を採用)

1. **repo の `render.py` を呼ぶ** (推奨、paper 視点と一致):

   ```bash
   pixi run python render.py \
     --model_path "$MODEL_PATH" \
     --source_path "$DATA_PATH" \
     --skip_train       # test cameras のみレンダリング
   # output: $MODEL_PATH/test/ours_<iter>/renders/*.png

   pixi run python /paper-reproduce-skills/scripts/render_gaussian_video.py \
     --frames-dir "$MODEL_PATH/test/ours_*/renders" \
     --output-mp4 reports/samples/output/recon_orbit.mp4 \
     --fps 30 --target-mb 12
   ```

   **NOTE (滑らかさ優先)**: `--target-mb` は 12 MB がデフォルト。動画サイズより **motion の連続性が大事** なので、`render_gaussian_video.py` は target 超過時に crf / 解像度だけ下げて **frame 数は絶対に削らない**。「2 秒スナップショット動画」のような出力は禁止。

2. **`render.py` が無い / interface が異なる場合**:
   - `<repo>/scripts/render_video.py` / `<repo>/eval.py --visualize` / `<repo>/demo.py` を順に試行
   - LLM が repo を grep して renderer entry point (`Scene.render` / `GaussianRasterizer` 等) を見つけ、最小スクリプトを `reports/_render_video.py` に書き出して実行

3. **どうしても render できない場合**:
   - PLY が standard なら interactive viewer のみ embed (従来通り、subsample は Step 4.6 適用)
   - PLY が non_standard なら sample 化を諦め、`samples.items` から外したうえで `samples.note` に `"非標準 3DGS のためブラウザ表示および動画レンダリング不可。フル PLY は <source_path>"` を記録

### Step 4.5.5-c: カメラ軌道

- repo の test cameras があればそれを使う (= paper の qualitative 比較と同じ視点)
- test cameras が無い場合: scene centroid を中心とした 360° 円軌道、120 frame、30 fps、elevation 固定 ~20°、半径 = `scene_diagonal × 1.2`。`reports/_orbit_cameras.py` に書き出して実行

### Step 4.5.5-d: report.json schema での扱い

video sample (主出力):

```json
{
  "type": "video",
  "label": "Reconstruction (rendered)",
  "input_paths": [],
  "output_paths": ["samples/output/recon_orbit.mp4"],
  "metadata": {
    "rendered_from": "output/exp1/point_cloud.ply",
    "render_method": "repo_render_py|repo_eval_visualize|custom_renderer|orbit_synthetic",
    "frames": 120,
    "fps": 30,
    "resolution": [1920, 1080],
    "ply_compatibility": "standard|non_standard",
    "ply_compatibility_reason": null,
    "source_path": "output/exp1/point_cloud.ply"
  }
}
```

- `is_standard=true` のときは **動画 + interactive viewer** を併用 embed (`samples.items` に 2 件、`type=video` と `type=gaussian_splat`)
- `is_standard=false` のときは **動画のみ** (`type=gaussian_splat` を出さない、ブラウザで歪む)

## Step 4.6: Gaussian PLY の byte 上限と subsample (interactive viewer 併用時のみ)

> P1-C により 3DGS の主出力は video に切り替わるため、本セクションは **standard PLY を `type=gaussian_splat` として interactive viewer 併用 embed する場合のみ** 適用。

`samples/output/*.ply` (gaussian_splat / point_cloud) のサイズは **15 MB** を hard limit とする。30k iter の `point_cloud.ply` は典型 100-300 MB なので、ブラウザ用 sample にはそのまま入れない (`samples/` の役割は「ブラウザ表示用」、フル解像度生成物は別)。

### 判定

byte 上限 (15 MB) のみで判定。点数で切らない (Gaussian PLY は SH 係数 / scale / rotation / opacity を含み点数と byte が線形でないため)。

**target は hard limit ぎりぎり (= 13 MB ≈ 87% of 15 MB) を狙う**。最初の voxel_size 推定でいきなり 1-2 MB に削ってしまうと、ブラウザビューワが極端にスパースになり「再構成が見えない」と苦情が来る (実フィードバック由来)。

### voxel_size 反復探索 (推奨フロー)

`voxel_down_sample` の voxel_size 1 発勝負ではなく、binary search で hard limit に近い voxel_size を見つける:

```python
import open3d as o3d, os
pcd = o3d.io.read_point_cloud(src)
HARD_LIMIT = 15 * 1024 * 1024
TARGET = 13 * 1024 * 1024  # 87% of hard limit

def write_size(p):
    o3d.io.write_point_cloud("/tmp/_probe.ply", p, write_ascii=False)
    return os.path.getsize("/tmp/_probe.ply")

lo, hi = 1e-4, 1.0
best = None
for _ in range(12):  # 12 回で 4096 倍の dynamic range をカバー
    v = (lo + hi) / 2
    sub = pcd.voxel_down_sample(v)
    sz = write_size(sub)
    if sz > HARD_LIMIT:
        lo = v          # まだ密すぎ → voxel を大きく
    elif sz < TARGET * 0.7:
        hi = v          # スパースすぎ → voxel を小さく
        best = (v, sub, sz)
    else:
        best = (v, sub, sz); break
```

最終的な `(voxel_size, sub, sampled_size_bytes)` を採用。`best` が `None` のまま終わったら最終値で採用 (= 探索が境界に張り付いた)。

### subsample 順 (順に試行)

1. **default = spatial (voxel-downsample)** — `open3d.geometry.PointCloud.voxel_down_sample(voxel_size)` で空間的に均一化。voxel_size は `(scene_diagonal / target_density)` から自動算出。Gaussian PLY は密度に強い偏りがあり、random だと前景 / 細部が消えやすい
2. **fallback = farthest-point sampling** — voxel が偏ったときの代替 (`open3d.geometry.PointCloud.farthest_point_down_sample(num_samples)`)
3. **最終 fallback = random** — 上記 2 つが利用不可なときのみ。seed 固定 (`np.random.seed(0)`)

### metadata schema

```json
"metadata": {
  "original_point_count": 1850000,
  "sampled_point_count": 48512,
  "original_size_bytes": 254800000,
  "sampled_size_bytes": 14700000,
  "sampling_method": "voxel_down_sample|farthest_point|random",
  "voxel_size": 0.012,
  "seed": null,
  "source_path": "output/exp1/point_cloud.ply"
}
```

`sampling_method=random` のときだけ `seed` を非 null。`source_path` はフル解像度の生成物への相対パス (リポ内に残す)。

### note フィールド

`samples.items[].note` または `samples.note` に、`$REPORT_LANG` に従って:
- ja: `"ブラウザビューワ用に空間サンプリング (voxel={voxel_size})。フル解像度は {source_path}"`
- en: `"Spatial subsample for browser viewer (voxel={voxel_size}). Full resolution at {source_path}"`

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
