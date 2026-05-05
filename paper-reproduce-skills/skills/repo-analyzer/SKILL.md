---
name: repo-analyzer
description: 論文 GitHub リポジトリ (CWD) の依存ファイル (environment.yml / requirements.txt / pyproject.toml / Dockerfile / setup.py) を検出し 6-Type (A1-F) に分類、CUDA / PyTorch 要求と GPU 互換性、feasibility (ok / degraded / infeasible) を reports/analysis.json に書き出す。/reimplement の Phase 1 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Glob Grep Write
---

# repo-analyzer: リポジトリ解析 + 6-Type 判定

CWD を解析し `reports/analysis.json` に出力。`reports/` は Phase 0 で作成済み。

## 出力言語

`overview.tagline` / `problem.input` / `problem.output` / `coord_convention.evidence` のような **読者向け散文** は環境変数 `$REPORT_LANG` (`ja` デフォルト / `en`) に従って書く。`overview.title`、`paper_url`、論文・ライブラリ名・コードシンボルは翻訳しない（原文ママ）。固定値 (`opencv`, `easy`, `medium`, `hard` などの enum 値) も翻訳しない。下記抽出方針の例は `ja` を想定しているので、`en` 指定時は同等の英語短文を生成する。

## Step 0.5: Project Overview 抽出

人間向けの 1-2 文要約と論文リンクを `analysis.json.overview` に記録。Phase 4 で `report.html` 冒頭に表示。

抽出項目:

| キー | 抽出方針 | フォールバック |
|---|---|---|
| `title` | `README.md` の最初の `^# ` 見出し | `null` |
| `tagline` | README から「このリポジトリ／論文が何をするものか」が読者に伝わる 1-2 文を要約 (最大 200 字、改行は半角空白に圧縮)。候補: H1 直下段落 / abstract / Introduction / "About" / "Overview"。直訳ではなく、必要なら複数箇所を統合してよい | `null` |
| `paper_url` | README 中の `arxiv.org/abs/` URL → プロジェクトページ URL | `null` |

抽出失敗時は当該フィールドを `null`。`title` が `repo_name` と完全一致する場合も `null`（重複表示回避）。

## Step 0.6: Problem Setting 抽出

「この手法の入力と出力は何か」を `analysis.json.problem` に記録。Phase 4 で `report.html` の Problem Setting セクションに表示する。レポートを開いた人が論文・コードを読まずに「どんなタスクか」を把握できるようにするため。

抽出項目:

| キー | 抽出方針 | フォールバック |
|---|---|---|
| `input` | 1-2 文で「何が入力か」を明記。データの種類・形式・暗黙の前処理仮定を含める。例: `"単一の RGB 画像（任意のアスペクト比）"`, `"ステレオ画像ペア (L/R, 同サイズ)"`, `"3-8 枚のマルチビュー画像（同一シーン）"` | `null` |
| `output` | 1-2 文で「何が出力か」を明記。形式・後処理が必要なら含める。例: `"画素ごとの depth map (float32, 入力と同じ H×W)"`, `"3D Gaussian splat (.ply)"`, `"再構成メッシュ (.glb)"` | `null` |

抽出元の優先順位: 論文 abstract → README の "Method" / "Overview" / "How it works" 節 → demo スクリプトの引数と出力 → analysis.json の他の手がかり (samples カテゴリ等)。

**取れなければ `null`**。捏造・推測禁止。誇張禁止（"high-quality" などの定性的な飾り文句は不要、形式と内容に絞る）。

## Step 0.7: 座標系規約の検出

3D 出力 (PLY / GLB / Gaussian Splatting / 点群) を持つ可能性のあるリポでは **OpenCV 規約 (X right, Y **down**, +Z forward) と OpenGL 規約 (X right, Y **up**, -Z forward) のどちらか** を判定し、`analysis.json.coord_convention` に記録する。Phase 4 で `report.html` の Three.js ビューワがこの値を見て X 軸 180° 回転 (`diag(1, -1, -1)`) を適用するか決める。これを誤ると **3D 出力が上下逆さま or 鏡像で表示される**。

### なぜ重要か

- **Y だけ反転は NG**: `det = -1` で左手系（鏡像）になる。点群だけなら見た目通っても、メッシュ法線・カメラ extrinsic・回転行列が後段で破綻
- 正しい変換は **X 軸 180° 回転 = `diag(1, -1, -1)`**（`det = +1`、純粋な回転）
- 3D 出力を持たないリポ (`rgb_to_rgb`, `mono_to_depth` 等) ではこの判定は不要 → `null` で OK

### 検出シグナル（強い順）

```bash
# 1. ビューワ/カメラの明示設定（最強の証拠）
grep -rE "set_up_direction\s*\(\s*\(?\s*[01]\.?\s*,\s*-1" --include="*.py" .   # viser y-down
grep -rE "camera(\.|_)?up\s*[:=]\s*\(?\s*[01]\.?\s*,\s*-1" --include="*.py" .  # PyOpenGL/Three.js camera.up=Y-down

# 2. コード/ドキュメントのコメント
grep -rEi "OpenCV (camera|coordinate|convention|world)" --include="*.py" --include="*.md" .
grep -rEi "Y[-_ ]?down|Z[-_ ]?forward" --include="*.py" --include="*.md" .

# 3. ヘリテージ（README 言及）
grep -iE "DUSt3R|MASt3R|VGGT|COLMAP|gaussian.splatting|MVSNet" README.md 2>/dev/null
```

### スキーマ

```json
"coord_convention": {
  "world": "opencv|opengl|z_up|unknown",
  "evidence": "string|null"
}
```

| world | 意味 |
|---|---|
| `opencv` | Y-down, +Z forward。CV 論文の標準 (DUSt3R, COLMAP, gaussian-splatting Inria, MVS 系) |
| `opengl` | Y-up, -Z forward。Three.js / Blender / Unity / DCC ツールから export した 3D |
| `z_up` | Z-up, -Y forward。古い Blender, ROS, 一部 USD |
| `unknown` | シグナルが取れず確信なし |

`evidence` は判定根拠の 1 行サマリ（例: `"viser set_up_direction in arc/viz/viser_visualizer_track.py"`、`"OpenCV comment in arc/models/utils/geometry.py:59"`、`"DUSt3R heritage"`）。

### 判定ルール

- 上記 3 シグナルの 1 つでも `Y-down` を示せば → `opencv`
- 明示的に Y-up 指定があれば → `opengl`
- Z-up 指定があれば → `z_up`
- どれも取れなければ → `unknown`

**3D 出力が無いリポでは `coord_convention` 全体を `null`** にして良い（dep_type が画像 in/out のみと判定される場合等）。

## Step 1: 依存ファイル検出

```bash
ls environment.yml environment.yaml conda_env.yml conda.yaml 2>/dev/null
ls requirements*.txt 2>/dev/null
ls pyproject.toml setup.py setup.cfg 2>/dev/null
find . -maxdepth 3 -iname "Dockerfile*" 2>/dev/null
```

Dockerfile の検索パスは `analysis.json.dockerfile_search_note` に記録。

## Step 2: defaults チャンネル検出

environment.yml / conda.yaml の `channels:` に `defaults` があれば `pixi_strategy` に記録（Phase 2 で除去）。

## Step 3: submodule 検出（Step 4 より先に実行）

```bash
git submodule status
```

各 submodule を `analysis.json.submodules[]` に記録:

- SSH URL (`git@github.com:`) → HTTPS に変換
- `has_setup_py`: `setup.py` / `pyproject.toml` の有無
- `has_cuda_extension`: `ext_modules` / `CUDAExtension` / `CppExtension` / `CMakeLists.txt` / `.cu` / `.cuh` のいずれか

Phase 2 で `[pypi-dependencies] name = { path, editable = true }` と `no-build-isolation` を注入。

## Step 4: 6-Type 判定

優先順位: A > C > B > E > D > F。

| Type | 条件 |
|---|---|
| A1 | environment.yml のみ、submodule pip deps 行なし |
| A2 | environment.yml + submodule 存在、または pip deps 行あり |
| A3 | environment.yml + requirements*.txt 併存 |
| C1 | pyproject.toml + `[build-system]` = setuptools/hatch/flit |
| C2 | pyproject.toml + `[tool.poetry]` |
| C3 | pyproject.toml + `[tool.pdm]` |
| B1 | `requirements*.txt` 1ファイルのみ、setup.py なし（ファイル名問わず） |
| B2 | `requirements*.txt` 1ファイル + setup.py（ルートまたはサブモジュール） |
| B3 | `requirements*.txt` 複数ファイル |
| E1 | setup.py 単独 |
| E2 | setup.cfg 単独 |
| E3 | setup.py + requirements*.txt（B にフォールバック） |
| D1 | Dockerfile + pip install |
| D2 | Dockerfile + conda install |
| D3 | Dockerfile + apt + pip 混在 |
| F | 依存ファイル皆無 |

B2 判定時、サブモジュールの setup.py は Step 3 の `has_setup_py` を参照。

## Step 5: CUDA / PyTorch バージョン特定

優先度順:

1. environment.yml / requirements.txt の torch 指定
2. Dockerfile の `FROM`（例: `nvidia/cuda:12.1.0-...`）
3. README.md
4. setup.py / pyproject.toml
5. ソース中のバージョンチェック

複数検出時の優先順位: environment.yml > Dockerfile > README。

## Step 6: デモコマンド特定

1. README.md の "Demo" / "Inference" / "Quick Start" / "Usage" 節
2. `demo.py` / `run.py` / `inference.py` / `test.py` / `eval.py`
3. `scripts/` 配下
4. Makefile の推論ターゲット

## Step 7: モデルダウンロード方法

`wget` / `curl` / `gdown` / `huggingface_hub` / カスタムスクリプトのいずれかを検出。

## Step 8: 難易度評価

| 難易度 | 条件 |
|---|---|
| easy | A1/B1/C1 + submodule なし + CUDA 不要 or 明示指定 |
| medium | A2/A3/B2/B3 + submodule or CUDA 拡張ビルド |
| hard | D/E/F、複数 submodule + C++/CUDA 拡張、依存情報不完全 |

## Step 9: CUDA↔PyTorch 互換チェック

Step 5 の cuda_version と torch version を互換マトリクスと照合。矛盾時は `analysis.json.cuda_torch_compat_mismatch = true` + 推奨値を記録。Phase 2 の attempt 1 は推奨値で開始。

## Step 9.5: GPU アーキテクチャ互換チェック

ホスト GPU の compute capability を取得し、要求 torch+CUDA wheel がそのカーネルを含むか確認。

```bash
nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1  # e.g. "12.0"
```

**原則**: prebuilt wheel はリリース時点の GPU アーキテクチャのカーネルのみ収録。wheel リリース後に登場した GPU 世代では `CUDA error: no kernel image is available` が発生し推論不可。

代表的な閾値:
- compute_cap ≤ 9.0: torch ≥ 2.0 + CUDA ≥ 11.8 で対応済み
- compute_cap ≥ 10.0: その世代を初めてサポートした torch+CUDA が必要

互換問題検出時は `analysis.json.gpu_arch_incompatible` に記録（`cuda_torch_compat_mismatch` と同形式）:

```json
"gpu_arch_incompatible": {
  "detected": true,
  "host_compute_cap": "12.0",
  "max_cc_for_required_torch": "9.0",
  "recommended_torch": "2.7.0",
  "recommended_cuda": "12.8"
}
```

`detected=false` 時は他フィールド省略可。

## Step 10: Feasibility 判定

README / 論文から最低要件を抽出しホスト実測値と突合。`analysis.json.feasibility` に記録。

抽出項目（README の "Requirements" / "Hardware" / "Setup" 節、論文の実験設定表）:

| キー | 例 | 抽出先 |
|---|---|---|
| `min_vram_gb` | 24 / 40 / 80 | "requires 24GB GPU", "A100 80GB" |
| `min_disk_gb` | 100 | datasets / weights サイズ合計 |
| `min_cuda` | "11.8" | "CUDA >= 11.8" |
| `needs_auth` | true | HuggingFace gated, Google Form |

ホスト実測:

```bash
nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1  # MiB
nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1           # compute capability
df -BG --output=avail . | tail -1
nvcc --version 2>/dev/null | grep -oP 'release \K[0-9.]+'
```

判定基準:

- `infeasible`: VRAM 不足かつ CPU fallback 不可 / ディスク不足 / 認証未設定 / 必須 URL が 4xx・5xx
- `degraded`: VRAM 不足だが CPU fallback 可 / URL 到達性のみ警告 / **`gpu_arch_incompatible.detected=true`（推奨アップグレードパスあり）**
- `ok`: 上記に非該当

`gpu_arch_incompatible.detected=true` → `degraded`。Phase 2 attempt 1 から推奨 torch+cuda でビルド試行（`cuda_torch_compat_mismatch` と同フロー）。依存非互換で全 attempt 消化時は Phase 4 で `failed` + `next_actions` に手動手順を記載。

`analysis.json.feasibility`:

```json
{
  "status": "ok|degraded|infeasible",
  "requirements": {"min_vram_gb": 24, "min_disk_gb": null, "min_cuda": "11.8", "needs_auth": false},
  "host": {"vram_gb": 12, "disk_gb": 200, "cuda": "12.1", "gpu_compute_cap": "12.0"},
  "blockers": ["gpu_arch_incompatible: host cc 12.0 > max cc 9.0 for torch 2.1.2+cu118; recommended torch>=2.6+cu128"],
  "has_readme_install_section": true
}
```

`has_readme_install_section`: `grep -niE '^##+ (install|installation|setup|getting started|requirements)' README.md` が 1 件以上ヒットで `true`。Type D/F の依存抽出難度シグナル。

## Step 11: reports/analysis.json 出力

全解析結果を `reports/analysis.json` に出力。スキーマは `/reimplement` の定義に従う。
