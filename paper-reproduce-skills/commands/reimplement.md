---
description: CV論文のGitHubリポジトリを全自動再現する。CWD=clone済みリポジトリで実行。
allowed-tools: Bash Read Write Edit Glob Grep Agent
---

# /reimplement — 論文リポジトリ全自動再現コマンド

あなたは CV 論文の GitHub リポジトリを Pixi 環境で全自動再現するエージェントです。
以下の Phase を順番に実行してください。**NEVER STOP**: 人間に「続けますか？」と聞かない。失敗しても自律的にリトライし続ける。手動停止されるまで止まらない。

---

## Phase 0: Initialize

1. `git status` で CWD が git リポジトリであることを確認
2. `git stash` で未コミット変更を退避（あれば）
3. リポジトリ名・URL を `git remote -v` から自動検出
4. `git submodule status` で submodule の有無を確認
5. attempts.tsv を初期化（ヘッダー行のみ書き込み）:
   ```
   attempt\tcommit\tphase\taction\tresult\terror_tier\terror_summary\tduration_s
   ```
6. `ls` で依存ファイル一覧を取得（Phase 1 の事前情報）
7. `.gitignore` に `attempts.tsv` を追加（git 管理外にする）

---

## Phase 1: リポジトリ解析

**repo-analyzer スキルを参照して実行。** 結果を `analysis.json` として出力。

analysis.json のスキーマ:

```json
{
  "repo_name": "string",
  "repo_url": "string",
  "dep_type": "A1|A2|A3|B1|B2|B3|C1|C2|C3|D1|D2|D3|E1|E2|E3|F",
  "dep_type_label": "string",
  "dep_files_found": {
    "environment_yml": "string|null",
    "requirements_txt": ["string"],
    "pyproject_toml": "string|null",
    "setup_py": "boolean",
    "setup_cfg": "boolean",
    "dockerfile": "string|null",
    "conda_yaml": "string|null"
  },
  "python_version": "string",
  "cuda_version": "string|null",
  "pytorch_version": "string|null",
  "submodules": [
    {
      "name": "string",
      "path": "string",
      "url": "string",
      "has_cuda_extension": "boolean"
    }
  ],
  "needs_no_build_isolation": ["string"],
  "demo_commands": ["string"],
  "model_download": {
    "method": "wget|gdown|huggingface|script",
    "details": "string"
  },
  "pixi_strategy": {
    "init_method": "pixi init --import|pixi init|pixi init --pyproject",
    "channels": ["string"],
    "torch_source": "pypi_wheel|conda_pytorch",
    "cuda_channel": "conda-forge|nvidia",
    "needs_divide_and_conquer": "boolean",
    "needs_no_build_isolation": ["string"],
    "needs_dep_conversion": "boolean",
    "conversion_source": "string|null"
  },
  "dockerfile_analysis": {
    "base_image": "string|null",
    "cuda_from_image": "string|null",
    "apt_packages": ["string"],
    "pip_commands": ["string"],
    "env_vars": {}
  },
  "difficulty": "easy|medium|hard"
}
```

---

## Phase 2: Pixi 環境構築

**pixi-env-builder スキル、dep-converter スキル、cuda-dependency-resolver スキルを参照して実行。**

analysis.json の `dep_type` に基づいて変換戦略を選択し、pixi.toml を生成する。各 Type の詳細フローは pixi-env-builder スキルに定義。変換ルールは dep-converter スキルに定義。CUDA 関連は cuda-dependency-resolver スキルに定義。

### Experiment Loop（NEVER STOP）

**experiment-loop スキルを参照して実行。**

```
while not succeeded:
  1. START_TIME=$(date +%s)  <- 省略禁止
  2. pixi.toml を生成/修正
  3. git add pixi.toml && git commit -m "attempt #{n}: {action}"
  4. pixi install 2>&1 | tee build.log
  5. END_TIME=$(date +%s) && DURATION=$((END_TIME - START_TIME))  <- 省略禁止
  6. attempts.tsv にログ追記（成功でも失敗でも必ず記録）  <- 省略禁止
  7. 結果判定:
     成功 -> advance + 環境検証 (python -c "import torch; print(torch.cuda.is_available())")
     失敗 -> diagnose + classify (experiment-loop スキルの 3-Tier 分類に従う)
  8. 失敗時: git reset --hard HEAD~1
```

**CRITICAL: ステップ1, 5, 6 は成功・失敗を問わず毎回必ず実行する。attempts.tsv への記録漏れは禁止。**

---

## Phase 3: 推論実行

**experiment-loop スキルを参照して実行。**

### Step 1: モデルダウンロード

analysis.json の `model_download` に基づいてモデルをダウンロード:

| method | 実行方法 |
|--------|---------|
| `wget` | `pixi run python -c "import urllib.request; ..."` or `wget` コマンド |
| `gdown` | `pixi run gdown {file_id} -O {output_path}` |
| `huggingface` | `pixi run python -c "from huggingface_hub import hf_hub_download; ..."` |
| `script` | README 記載のダウンロードスクリプトを実行 |

**gdown --folder の注意（二重ネスト問題）:**
- `gdown --folder URL -O /workspace/weights/` は `/workspace/weights/weights/` になる
- 回避策: 一時ディレクトリにダウンロード後、中身を目的のパスに移動

**ダウンロード失敗時:**
- URL が切れている -> README の代替リンクを探す、HuggingFace Hub を検索
- 認証が必要 -> Tier 3 としてレポートに記載
- 容量が大きすぎる -> 軽量版モデルがあれば代替

### Step 2: Headless GUI 対策

Docker コンテナ内は headless 環境。experiment-loop スキルの「Headless 環境対策」セクションに従って、cv2/open3d/matplotlib のモンキーパッチを適用。

### Step 3: デモ/推論スクリプト実行 (Experiment Loop)

```
while not inference_succeeded:
  1. START_TIME=$(date +%s)  <- 省略禁止
  2. スクリプト修正 or パラメータ変更
  3. git add -A && git commit -m "attempt #{n}: {action}"
  4. pixi run python {demo_command} 2>&1 | tee inference.log
  5. END_TIME=$(date +%s) && DURATION=$((END_TIME - START_TIME))  <- 省略禁止
  6. attempts.tsv にログ追記  <- 省略禁止
  7. 結果判定:
     成功（出力ファイルが生成された）-> Phase 4 へ
     失敗 -> experiment-loop スキルの 3-Tier 分類に従う:
       Tier 1: auto-fix -> retry
       Tier 2: OOM fallback (5段階) -> retry
       Tier 3: report に記載 -> Phase 4 へ（status = partial or failed）
  8. 失敗時: git reset --hard HEAD~1
```

---

## Phase 4: レポート生成

### Step 1: 中間ファイルのクリーンアップ

一時ファイルを削除:
- `cleaned.yml`（Type A2/A3 で作成）
- `build.log`, `inference.log`（ログは attempts.tsv に集約済み）
- `_headless_patch.py`（Phase 3 で作成した場合）

### Step 2: report.json 生成（機械可読）

```json
{
  "repo_name": "string",
  "repo_url": "string",
  "status": "success|partial|failed",
  "dep_type": "string",
  "dep_type_label": "string",
  "total_attempts": "number",
  "duration_total_s": "number",
  "pixi_toml_hash": "string",
  "inference_output": "string|null",
  "errors": ["string"],
  "plugin_version": "1.0.0"
}
```

**status の判定基準:**
- `success`: pixi install 成功 + 推論実行成功（出力ファイルが生成された）
- `partial`: pixi install 成功 + 推論未実行 or 一部成功
- `failed`: pixi install 失敗、または推論が根本的に動作しない

**duration_total_s**: attempts.tsv の全 duration_s を合算。

### Step 3: report.html 生成（目視確認用）

**templates/report.html テンプレートを参照して生成する。**

テンプレート内のプレースホルダーを実際の値で置換する:

| プレースホルダー | 値の取得元 |
|---|---|
| `{{REPO_NAME}}` | analysis.json の `repo_name` |
| `{{REPO_URL}}` | analysis.json の `repo_url` |
| `{{TIMESTAMP}}` | 現在の日時 (ISO 8601) |
| `{{STATUS}}` | report.json の `status` |
| `{{DEP_TYPE}}` | analysis.json の `dep_type` + `dep_type_label` |
| `{{TOTAL_ATTEMPTS}}` | attempts.tsv のデータ行数 |
| `{{DURATION_TOTAL}}` | 全 duration_s の合算（人間可読形式: "2m 34s"） |
| `{{ATTEMPTS_ROWS}}` | attempts.tsv の各行を `<tr>` に変換 |
| `{{ARTIFACTS_LIST}}` | 生成物ファイルの `<li>` リスト |
| `{{PIXI_TOML_CONTENT}}` | pixi.toml の内容（HTML エスケープ済み） |
| `{{ERRORS_LIST}}` | エラーの `<li>` リスト（`failed`/`partial` 時のみ） |
| `{{PLUGIN_VERSION}}` | plugin.json の `version` |

**ASSERTION: report.html の `<tr>` 行数 == attempts.tsv のデータ行数。不一致は禁止。**

### Step 4: 成果物の保持

以下のファイルをリポジトリルートに保持:
- `pixi.toml` + `pixi.lock`（環境の完全な再現に必要）
- `analysis.json`（解析結果）
- `attempts.tsv`（全試行ログ）
- `report.json` + `report.html`（レポート）

---

## 核心原則

### NEVER STOP
- 環境構築に失敗しても止まらない — Tier 分類に従って自律的に修正・再試行
- 推論に失敗しても止まらない — OOM フォールバック -> パラメータ変更 -> CPU fallback
- 唯一の停止条件: 全 Phase 完了、または人間による手動停止

### denkiwakame ワークフロー準拠
- **Divide-and-Conquer**: submodule は最初に除外し、ベース構築後に1つずつ追加
- **no-build-isolation**: PEP517 違反の submodule (C++/CUDA 拡張) に必須
- **CUDA は1つに統一**: wheel/conda/docker/host の4つが混在するサバンナを整理
- **defaults チャンネル除去**: miniconda 由来で混入しがちだが有償かつ不要
- **conda-forge を基本チャンネル**: ただし元 repo が conda pytorch を使う場合は pytorch/nvidia チャンネルも許容
- **gcc/gxx も pixi 管理下に**: nvidia channel の CUDA では gcc/g++ が外側から見えない
- **system-requirements.cuda**: ホストドライバ要件の申告であり、pixi 環境内の CUDA バージョンとは別物
