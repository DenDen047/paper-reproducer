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

## Step 7.5: データ取得可否の分類 (data_acquisition_table)

論文の主要 claim を再現するには重み (Step 7) だけでなく **dataset** が要る。「重みなし + データ大量 → 一律 degraded」という粗い判定をやめ、dataset 単位で 5 段階に分類して `analysis.json.data_acquisition_table[]` に出力する。Phase 3 はこの表を見て、`auto-fetch` 判定済みの dataset を無条件で取得する (= ユーザー対話を発生させない)。

### 5 段階分類

| category | 判定 |
|---|---|
| `bundled` | リポジトリに同梱 (`data/` / `examples/` / submodule)。zero-fetch |
| `auto-fetch` | gdown / wget / huggingface-hub / curl で probe 済み reachable |
| `assisted` | 取得手順は明確だが COLMAP / Blender 等の事前ツールや前処理スクリプトが必要 |
| `gated` | HuggingFace login / NUS 登録 / Google Form 等の認証が必要 |
| `blocked` | 非公開 / 恒常的なレート制限 / 著者対応待ち |

### 判定手順 (二段階)

**第 1 段 (LLM 推論)**: README / リポ構造から各 dataset の category の **draft** を出す。論文 Table の行数 (`DTU`, `TnT`, `MipNeRF360` 等) や README の "Datasets" / "Data Preparation" 節を参照。

**第 2 段 (probe)**: draft を `scripts/probe_dataset.py` で機械検証する。probe 結果が draft を上書きする (例: README で「直 HTTP」と書いてあっても 4xx なら `blocked`)。

```bash
# auto モード = URL 形状から method を自動判定 (http_head / gdown_dry_run / hf_api)
pixi run python /paper-reproduce-skills/scripts/probe_dataset.py \
  --url "$DATASET_URL" \
  --output reports/_probe_${i}.json
```

probe スクリプトは `gdown` / `huggingface_hub` 未インストールでも exit 0 を返し `reachable=false` の JSON を書く (再現フローを止めない)。

**probe 結果による降格ルール**:

| probe 結果 | 上書き後 category |
|---|---|
| `http_status` 4xx / `gdown rate-limited` / `hf gated` | `blocked` (非永続。24h 後に再試行する余地あり) |
| `hf gated/auth` で 401 | `gated` (ユーザー対話で解決可能) |
| `reachable=true` + `content_length` 取得 | `auto-fetch` 確定 |

### dataset entry スキーマ

`analysis.json.data_acquisition_table[]` に各 dataset を 1 行で出す:

```json
{
  "name": "DTU Points.zip",
  "url": "https://roboimagedata2.compute.dtu.dk/.../Points.zip",
  "size_gb_estimated": 6.3,
  "size_gb_probed": 6.3,
  "probe": {
    "method": "http_head|gdown_dry_run|hf_api|none",
    "reachable": true,
    "checked_at": "2026-05-06T12:34:56Z",
    "evidence": "HTTP 200, content-length=6300000000"
  },
  "category": "bundled|auto-fetch|assisted|gated|blocked",
  "required_for_claims": ["DTU Chamfer", "DTU PSNR"],
  "preprocess": "none|repo_script|external_tool",
  "disk_after_extract_gb": 18.0
}
```

| フィールド | 説明 |
|---|---|
| `name` | dataset / file の人間可読な識別子 |
| `url` | 取得元 URL (gated / blocked でも記録) |
| `size_gb_estimated` | README / 論文記載値。なければ `null` |
| `size_gb_probed` | probe で取れた `content_length / 1e9`。圧縮 archive のとき `disk_after_extract_gb` は別途見積もる |
| `probe` | `scripts/probe_dataset.py` の出力をそのまま転記 |
| `required_for_claims` | この dataset がサポートする論文 claim ID の配列 (`paper_claims[].id` と紐付く)。空配列 = `optional` |
| `preprocess` | `none` / `repo_script` (リポ内 `convert_*.py` 等) / `external_tool` (COLMAP / Blender 等が必須) |
| `disk_after_extract_gb` | 展開後の必要ディスク。圧縮率不明なら `size_gb_probed × 2.5` を fallback |

`required_for_claims` は **必須 / optional の二択でなく、どの claim を支えるか** を列挙する。Phase 4 status 集約と P2-B (GDrive レート制限の取り扱い) で参照される。

### 出力規約

- 1 dataset = 1 entry。同じ archive を分割 DL する場合 (`Points.zip`, `SampleSet.zip`) は別 entry
- bundled なら `url` / `probe` を `null` でよい
- 大きい probe 文字列 (リダイレクト連鎖の HTTP 履歴等) は `evidence` に 200 字以内で要約

## Step 7.6: 再現モード判定 (reproduction_mode)

論文 claim の再現に **full training が必要か** を判定し `analysis.json.reproduction_mode` に格納する。Phase 3.5 (Full Training) はこの値を見て smoke 後に full を起動するか決める。

| 値 | 判定基準 |
|---|---|
| `inference_only` | 提供 checkpoint URL が README / Hugging Face Hub にあり、README quickstart が `inference` / `demo` から始まる |
| `train_required` | 提供 checkpoint なし / 主要 claim が「学習結果」(Table N に train scratch とあり) / `train.py` に iter ループ + default `--iterations` あり |
| `train_optional` | checkpoint も train script も両方ある (= ユーザーが選択可能、Phase 3.5 を skip) |

判定シグナル:

```bash
# 提供 checkpoint URL の有無
grep -niE 'checkpoint|pretrained|weights|\.pth|\.ckpt|hf_hub_download' README.md | head -5

# train script に iter / epoch ループがあるか
for f in train.py main.py scripts/train*.py; do
    [ -f "$f" ] || continue
    grep -qE "for\s+(iter|epoch|step|i)\s+in\s+range" "$f" && echo "loop in $f"
    grep -qE "argparse.*--(iterations|max_steps|epochs|max_iter)" "$f" && echo "iter arg in $f"
done

# README quickstart が train で始まるか
grep -niE '^(##|###)\s*(quickstart|quick start|usage|getting started)' README.md | head -3
```

`train_required` 判定時は同時に `analysis.json.training_recovery` を埋める (Phase 3.5 が resume_arg として使う):

```json
"training_recovery": {
  "checkpoint_interval_iters": 7500,
  "checkpoint_dir_pattern": "output/<exp>/point_cloud/iteration_<N>/",
  "resume_arg": "--start_checkpoint output/<exp>/chkpnt7500.pth"
}
```

抽出元は `train.py` の `--save_iterations` / `--checkpoint_iterations` 等の default、または README の resume 例。取れなければ各フィールド `null`。

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

判定基準 (上から順に評価):

1. **必須 dataset の取得可否を Step 7.5 の `data_acquisition_table` から導出**:
   - 必須 = `required_for_claims` が非空 (= 主要 claim をサポートする dataset)
   - 必須 dataset 集合 (= unique union over claims) を「最小 dataset セット」とする
2. **判定**:
   - `infeasible`: VRAM 不足かつ CPU fallback 不可 / ディスク不足 / 認証未設定 / **必須 dataset 集合の全エントリが `gated` または `blocked`** (= claim を支える代替 dataset がない)
   - `degraded`: VRAM 不足だが CPU fallback 可 / URL 到達性のみ警告 / `gpu_arch_incompatible.detected=true`（推奨アップグレードパスあり）/ **必須 dataset の一部が `gated` / `blocked` だが他で代替可能、または optional dataset のみ落ちる**
   - `ok`: 上記に非該当 (必須 dataset は全て `bundled` / `auto-fetch` / `assisted` で reachable)

「必須 claim 用 dataset が全部 `blocked`」は infeasible、「optional だけ落ちる」は ok を維持、というのが粗さ解消の核。

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

## Step 10.5: GitHub slug 抽出

`repo_url` (= `git remote get-url origin` を HTTPS 化したもの) から `owner/repo` 形式のスラッグを取り出し、`analysis.json.github_slug` に格納する。Phase 3 の `experiment-loop` と Phase 4 Step 1.8 が `gh search --repo "$github_slug"` で参照する。

```bash
# 例: https://github.com/animotionlab26/MocapAnything[.git] → animotionlab26/MocapAnything
GITHUB_SLUG=$(echo "$REPO_URL" \
  | sed -E 's#^git@github\.com:#https://github.com/#' \
  | sed -E 's#^https?://github\.com/##' \
  | sed -E 's#\.git$##' \
  | sed -E 's#/$##')
# owner/repo の形になっていなければ null
if ! echo "$GITHUB_SLUG" | grep -qE '^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$'; then
  GITHUB_SLUG=""
fi
```

GitHub 以外のホスティング (gitlab.com, bitbucket.org, 自己ホスト等) は対象外 → `null`。`gh` は GitHub 専用なので、ここで弾くことで Phase 3 / Phase 4 が無駄な検索を投げないようにする。

スキーマ:

```json
"github_slug": "owner/repo|null"
```

## Step 11: reports/analysis.json 出力

全解析結果を `reports/analysis.json` に出力。スキーマは `/reimplement` の定義に従う。
