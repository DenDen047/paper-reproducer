---
description: CV論文のGitHubリポジトリを全自動再現する。CWD=clone済みリポジトリで実行。
allowed-tools: Bash Read Write Edit Glob Grep Agent
---

# /reimplement — 論文リポジトリ全自動再現コマンド

あなたは CV 論文の GitHub リポジトリを Pixi 環境で全自動再現するエージェントです。
以下の Phase を順番に実行してください。**NEVER STOP**: 人間に「続けますか？」と聞かない。失敗しても自律的にリトライし続ける。手動停止されるまで止まらない。

---

## Phase 0: Initialize

### 成果物レイアウト（全 Phase 共通）

```
{repo_root}/
├── pixi.toml            # 再現環境本体（ルート直下、commit 対象）
├── pixi.lock            # 同上
└── reports/             # レポート系成果物の集約先
    ├── analysis.json    # Phase 1 解析結果
    ├── attempts.tsv     # 全試行ログ（git 管理外）
    ├── report.json      # Phase 4 機械可読レポート
    ├── report.html      # Phase 4 目視確認レポート
    └── samples/         # Phase 4 入出力サンプル（report.html が参照）
        ├── input/
        └── output/

# リポジトリ外（Phase 4 Step 5、status=success のみ）
../{repo_name}-{short_sha}.tar.gz  # git archive による状態スナップショット
```

### 初期化手順

1. `git status` で CWD が git リポジトリであることを確認
2. `git stash` で未コミット変更を退避（あれば）
3. リポジトリ名・URL を `git remote -v` から自動検出
4. `git submodule status` で submodule の有無を確認
5. `mkdir -p reports`
6. `reports/attempts.tsv` を初期化（ヘッダー行のみ書き込み）:
   ```
   attempt\tcommit\tphase\taction\tresult\terror_tier\terror_summary\tduration_s
   ```
7. `.gitignore` に `reports/attempts.tsv` を追加
8. `ls` で依存ファイル一覧を取得（Phase 1 の事前情報）

---

## Phase 1: リポジトリ解析

**repo-analyzer スキルを参照して実行。** 結果を `reports/analysis.json` として出力。

reports/analysis.json のスキーマ:

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

`reports/analysis.json` の `dep_type` に基づいて変換戦略を選択し、pixi.toml を生成する。各 Type の詳細フローは pixi-env-builder スキルに定義。変換ルールは dep-converter スキルに定義。CUDA 関連は cuda-dependency-resolver スキルに定義。

### Experiment Loop（NEVER STOP）

**experiment-loop スキルを参照して実行。**

```
while not succeeded:
  1. START_TIME=$(date +%s)  <- 省略禁止
  2. pixi.toml を生成/修正
  3. git add pixi.toml && git commit -m "attempt #{n}: {action}"
  4. pixi install 2>&1 | tee build.log
  5. END_TIME=$(date +%s) && DURATION=$((END_TIME - START_TIME))  <- 省略禁止
  6. reports/attempts.tsv にログ追記（成功でも失敗でも必ず記録）  <- 省略禁止
  7. 結果判定:
     成功 -> advance + 環境検証 (python -c "import torch; print(torch.cuda.is_available())")
     失敗 -> diagnose + classify (experiment-loop スキルの 3-Tier 分類に従う)
  8. 失敗時: git reset --hard HEAD~1
```

**CRITICAL: ステップ1, 5, 6 は成功・失敗を問わず毎回必ず実行する。reports/attempts.tsv への記録漏れは禁止。**

---

## Phase 3: 推論実行

**experiment-loop スキルを参照して実行。**

### Step 1: モデルダウンロード

`reports/analysis.json` の `model_download` に基づいてモデルをダウンロード:

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
  6. reports/attempts.tsv にログ追記  <- 省略禁止
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
- `build.log`, `inference.log`（ログは reports/attempts.tsv に集約済み）
- `_headless_patch.py`（Phase 3 で作成した場合）

### Step 1.5: 使い方情報の抽出

**usage-documenter スキルを参照して実行。** 再現したリポジトリの使い方を 3 段階（Quickstart / 発展的 / 開発者向け）で抽出し、`usage` オブジェクトを生成する。Step 2 で `reports/report.json` に組み込む。

### Step 1.6: 入出力サンプルの抽出

**sample-embedder スキルを参照して実行。** Phase 3 の成功コマンドから入出力ファイルを特定し、`reports/samples/` 配下に正規化コピーして `samples` オブジェクトを生成する。Step 2 で `reports/report.json` に組み込む。

### Step 1.7: Next Actions の生成

再現作業後にユーザーが次に取るべきアクションを `next_actions` 配列として生成する。Step 2 で `reports/report.json` に組み込み、Step 3 で `report.html` にレンダリングし、Step 5 でターミナルに出力する（3 か所で同一ソース）。

**生成規則（status 別）:**

- **success** の場合（典型 2–4 件）:
  - 検証済み quickstart コマンドを自分のデータで試す提案（`usage.quickstart.command` があれば `command` に転記）
  - `usage.advanced` で未検証のものを動かしてみる提案
  - `samples` に含まれる出力を別の入力で再生成する提案
  - ベンチマーク・評価スクリプトがあれば実行提案

- **partial** の場合（典型 3–5 件、high/medium 中心）:
  - 未達の Phase を特定する指示（例: モデルが DL できていない、推論が部分成功）
  - `errors` を解消する具体的な手順（ファイル名・コマンド付き）
  - 軽量パラメータで先に動作確認する提案

- **failed** の場合（典型 3–6 件、high 中心）:
  - 失敗 Tier に応じた根本原因の説明と次のデバッグ手順
  - 代替アプローチ（別チャンネル、別バージョン、Docker フォールバック等）
  - `errors` の各項目に対応する具体的な修正候補

**next_actions 配列のスキーマ:**

```json
[
  {
    "priority": "high|medium|low",
    "action": "string",        // 何をすべきか（命令形、1 文）
    "reason": "string",        // なぜそれが次か（1–2 文）
    "command": "string|null"   // そのまま貼れば動くコマンド。該当なければ null
  }
]
```

**原則:**
- 各項目は独立して実行可能にする（前後依存が強い場合は 1 項目にまとめる）
- `action` は具体的に書く（×「環境を修正する」／○「`pixi add --pypi xformers==0.0.23` を追加してリビルド」）
- 結果が何もなくても空配列 `[]` ではなく最低 1 件は出す（`success` の場合でも「自分のデータで試す」等を入れる）
- 優先度は `high` が 0–2 件、過剰に high を付けない

### Step 2: reports/report.json 生成（機械可読）

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
  "usage": {
    "quickstart": {
      "description": "string",
      "command": "string",
      "verified": "boolean",
      "note": "string|null"
    } | null,
    "advanced": [
      {
        "title": "string",
        "command": "string",
        "verified": "boolean",
        "source": "string",
        "note": "string|null"
      }
    ],
    "developer": {
      "description": "string",
      "sample_code": "string",
      "import_path": "string",
      "note": "string|null"
    } | null
  },
  "samples": {
    "category": "rgb_to_rgb|mono_to_depth|stereo_to_depth|mv_to_gaussians|images_to_pointcloud|image_to_mask|image_to_bbox|image_to_keypoint|frames_to_flow|image_to_mesh|mv_to_nerf|video_output|unknown",
    "items": [
      {
        "type": "image_pair|image_triple|gaussian_splat|point_cloud|mesh|video",
        "label": "string",
        "input_paths": ["string"],
        "output_paths": ["string"],
        "metadata": {}
      }
    ],
    "note": "string|null"
  },
  "next_actions": [
    {
      "priority": "high|medium|low",
      "action": "string",
      "reason": "string",
      "command": "string|null"
    }
  ],
  "archive_path": "string|null",
  "plugin_version": "1.0.0"
}
```

**usage フィールド:** Step 1.5 で生成した usage オブジェクトをそのまま埋め込む。抽出できなかった階層は `null` を入れる（`advanced` のみ空配列 `[]`）。スキーマ詳細は usage-documenter スキルを参照。

**samples フィールド:** Step 1.6 で生成した samples オブジェクトをそのまま埋め込む。パスは `reports/` からの相対（例: `samples/input/left.png`）。カテゴリ判定・変換ルールは sample-embedder スキルを参照。

**next_actions フィールド:** Step 1.7 で生成した next_actions 配列をそのまま埋め込む。`report.json` を単一ソース (SSOT) とし、`report.html` とターミナル出力 (Step 6) はここから読み出してレンダリングする。

**archive_path フィールド:** Step 5 で生成されるアーカイブファイルのパス（リポジトリ親ディレクトリからの絶対パス）。status != "success" の場合や archive 作成がスキップされた場合は `null`。Step 2 時点では `null` を仮置きし、Step 5 でアーカイブ作成後に `report.json` を更新する（成功時のみ）。

**status の判定基準:**
- `success`: pixi install 成功 + 推論実行成功（出力ファイルが生成された）
- `partial`: pixi install 成功 + 推論未実行 or 一部成功
- `failed`: pixi install 失敗、または推論が根本的に動作しない

**duration_total_s**: reports/attempts.tsv の全 duration_s を合算。

### Step 3: reports/report.html 生成（目視確認用）

**templates/report.html テンプレートを参照して生成する。** テンプレートと同じディレクトリにある `templates/view.sh` も `reports/view.sh` として同時にコピーし実行権限を付与する（`chmod +x reports/view.sh`）。`view.sh` は `python3 -m http.server` を起動して `report.html` を HTTP 経由で開けるようにするためのヘルパで、3D ビューワ (CORS 対策) を動かすのに必要。

テンプレート内のプレースホルダーを実際の値で置換する:

| プレースホルダー | 値の取得元 |
|---|---|
| `{{REPO_NAME}}` | reports/analysis.json の `repo_name` |
| `{{REPO_URL}}` | reports/analysis.json の `repo_url` |
| `{{TIMESTAMP}}` | 現在の日時 (ISO 8601) |
| `{{STATUS}}` | reports/report.json の `status` |
| `{{DEP_TYPE}}` | reports/analysis.json の `dep_type` + `dep_type_label` |
| `{{TOTAL_ATTEMPTS}}` | reports/attempts.tsv のデータ行数 |
| `{{DURATION_TOTAL}}` | 全 duration_s の合算（人間可読形式: "2m 34s"） |
| `{{ATTEMPTS_ROWS}}` | reports/attempts.tsv の各行を `<tr>` に変換 |
| `{{ARTIFACTS_LIST}}` | 生成物ファイルの `<li>` リスト |
| `{{QUICKSTART_BLOCK}}` | `usage.quickstart` を HTML にレンダリング（後述） |
| `{{ADVANCED_BLOCK}}` | `usage.advanced` を HTML にレンダリング（後述） |
| `{{DEVELOPER_BLOCK}}` | `usage.developer` を HTML にレンダリング（後述） |
| `{{SAMPLES_BLOCK}}` | `samples.items` を HTML にレンダリング（後述） |
| `{{NEXT_ACTIONS_BLOCK}}` | `next_actions` を HTML にレンダリング（後述） |
| `{{PIXI_TOML_CONTENT}}` | pixi.toml の内容（HTML エスケープ済み） |
| `{{ERRORS_LIST}}` | エラーの `<li>` リスト（`failed`/`partial` 時のみ） |
| `{{PLUGIN_VERSION}}` | plugin.json の `version` |

**ASSERTION: reports/report.html の `<tr>` 行数 == reports/attempts.tsv のデータ行数。不一致は禁止。**

#### usage ブロックのレンダリング規則

**`{{QUICKSTART_BLOCK}}`** — `usage.quickstart` が非 null の場合:
```html
<p>{description}</p>
<pre><code>{command}</code></pre>
<p class="usage-note">{verified ? '<span class="usage-verified">✓ Phase 3 で動作確認済み</span>' : note}</p>
```
null の場合:
```html
<p class="usage-empty">Quickstart コマンドを特定できませんでした。</p>
```

**`{{ADVANCED_BLOCK}}`** — `usage.advanced` の各要素を順に:
```html
<h4>{title}</h4>
<pre><code>{command}</code></pre>
<p class="usage-note">出典: {source}{note ? ' — ' + note : ''}</p>
```
空配列の場合:
```html
<p class="usage-empty">追加の使い方は見つかりませんでした。</p>
```

**`{{DEVELOPER_BLOCK}}`** — `usage.developer` が非 null の場合:
```html
<p>{description}</p>
<pre><code>{sample_code}</code></pre>
<p class="usage-note">Import: <code>{import_path}</code>{note ? ' — ' + note : ''}</p>
```
null の場合:
```html
<p class="usage-empty">API としての利用想定は見つかりませんでした。Quickstart のスクリプト直接呼び出しを推奨。</p>
```

**HTML エスケープ必須**: `command` / `sample_code` / 各 `description` / `note` 中の `<`, `>`, `&`, `"`, `'` は必ずエスケープする。

#### samples ブロックのレンダリング規則

**`{{SAMPLES_BLOCK}}`** — `samples.items` を順に:

**`type == "image_pair"`:**
```html
<div class="sample-item">
  <h4>{label}</h4>
  <div class="sample-grid sample-grid-2">
    <figure><img src="{input_paths[0]}" alt="input" loading="lazy"><figcaption>Input</figcaption></figure>
    <figure><img src="{output_paths[0]}" alt="output" loading="lazy"><figcaption>Output</figcaption></figure>
  </div>
</div>
```

**`type == "image_triple"`:**
```html
<div class="sample-item">
  <h4>{label}</h4>
  <div class="sample-grid sample-grid-3">
    <figure><img src="{input_paths[0]}" alt="left" loading="lazy"><figcaption>Left</figcaption></figure>
    <figure><img src="{input_paths[1]}" alt="right" loading="lazy"><figcaption>Right</figcaption></figure>
    <figure><img src="{output_paths[0]}" alt="disparity" loading="lazy"><figcaption>Disparity</figcaption></figure>
  </div>
</div>
```

**`type == "gaussian_splat"`:**
```html
<div class="sample-item">
  <h4>{label}</h4>
  <div class="viewer-3d viewer-gsplat" data-src="{output_paths[0]}"></div>
  <p class="usage-note">3D Gaussians: {metadata.gaussian_count}</p>
</div>
```
ビューワ本体は template 末尾の `<script type="module">` で動的初期化される（Three.js + `@mkkellogg/gaussian-splats-3d` を CDN から importmap 経由で読み込む）。

**`type == "point_cloud"`:**
```html
<div class="sample-item">
  <h4>{label}</h4>
  <div class="viewer-3d viewer-pointcloud" data-src="{output_paths[0]}"></div>
  <p class="usage-note">Points: {metadata.point_count}</p>
</div>
```
ビューワ本体は template 末尾の `<script type="module">` で動的初期化される（Three.js `PLYLoader` + `THREE.Points`）。

**`type == "mesh"`:**
```html
<div class="sample-item">
  <h4>{label}</h4>
  <div class="viewer-3d viewer-mesh" data-src="{output_paths[0]}"></div>
  <p class="usage-note">Format: {metadata.format}</p>
</div>
```
ビューワ本体は template 末尾の `<script type="module">` で動的初期化される（Three.js `GLTFLoader` or `OBJLoader`）。対応拡張子: `.glb` / `.gltf` / `.obj`。

**`type == "video"`:**
```html
<div class="sample-item">
  <h4>{label}</h4>
  <video class="sample-video" src="{output_paths[0]}" autoplay muted loop playsinline preload="metadata">
    お使いのブラウザは HTML5 video に対応していません。
  </video>
</div>
```
JavaScript 不要、HTML5 `<video>` タグのみで再生。

`items` が空配列の場合:
```html
<p class="usage-empty">サンプルを取得できませんでした{note ? '（' + note + '）' : ''}。</p>
```

**HTML エスケープ必須**: `label`, `note` 中の `<`, `>`, `&`, `"`, `'` をエスケープ。`src` のパスは HTML 属性値としてエスケープ（`"` は `&quot;`）。

#### next_actions ブロックのレンダリング規則

**`{{NEXT_ACTIONS_BLOCK}}`** — `next_actions` の各要素を順に:

```html
<div class="next-action-item">
  <div class="next-action-header">
    <span class="priority-badge priority-{priority}">{priority}</span>
    <strong>{action}</strong>
  </div>
  <p class="usage-note">{reason}</p>
  <!-- command が非 null の場合のみ: -->
  <pre><code>{command}</code></pre>
</div>
```

空配列の場合:

```html
<p class="usage-empty">特筆すべき次のアクションはありません。</p>
```

**HTML エスケープ必須**: `action`, `reason`, `command` 中の `<`, `>`, `&`, `"`, `'` をエスケープ。

### Step 4: 成果物の確認

Phase 0 の「成果物レイアウト」のとおりに全ファイルが揃っていることを確認する。

### Step 5: 最終コミットとアーカイブ

**ローカルアーカイブとしてリポジトリ外に保存**し、後から自由に展開・検証できるようにする。

#### Step 5.1: 未コミット変更の最終コミット

Phase 4 で生成したレポート類 (`reports/report.json`, `reports/report.html`, `reports/samples/...`) はまだワーキングツリーに残っているはず。これらを 1 コミットにまとめる:

```bash
git status --porcelain
# 何か出たら:
git add reports/ pixi.toml pixi.lock
git commit -m "chore: finalize reproduction reports"
```

`reports/attempts.tsv` は `.gitignore` 対象なので対象外。既にクリーンなら何もしない（空コミットは作らない）。

#### Step 5.2: アーカイブ作成（`status == "success"` の場合のみ）

`reports/report.json` の `status` フィールドを確認し、`"success"` の場合のみ以下を実行する。`partial` / `failed` の場合は Step 5.2 をスキップし、`archive_path` を `null` のままにする。

```bash
REPO_NAME=$(basename "$PWD")
SHORT_SHA=$(git rev-parse --short HEAD)
ARCHIVE_PATH="$(cd .. && pwd)/${REPO_NAME}-${SHORT_SHA}.tar.gz"

git archive \
  --format=tar.gz \
  --prefix="${REPO_NAME}-${SHORT_SHA}/" \
  HEAD \
  -o "${ARCHIVE_PATH}"

ls -lh "${ARCHIVE_PATH}"
```

**挙動の注意:**
- `git archive HEAD` は**追跡ファイルのみ**をアーカイブする。`.gitignore` 対象のファイル（`reports/attempts.tsv`, `.pixi/`, ダウンロード済みモデル重みなど）は含まれない。
- モデル重みはアーカイブ展開後に Phase 3 Step 1 の手順で再ダウンロードする前提。これは意図的（アーカイブサイズを小さく保つため）。
- 親ディレクトリに書き込めない場合は `/tmp/${REPO_NAME}-${SHORT_SHA}.tar.gz` にフォールバックする。
- アーカイブは `{REPO_NAME}-{SHORT_SHA}/` というプレフィックスを持ち、展開すると同名ディレクトリが作られる。

#### Step 5.3: report.json の archive_path 更新

アーカイブ作成に成功したら、`reports/report.json` の `archive_path` フィールドを実際のパスに書き換えて新規コミットする:

```bash
# report.json を編集して archive_path を設定
git add reports/report.json
git commit -m "chore: record archive path"
```

**注意事項:**
- `--amend` は使わない（核心原則「Git 運用ルール」参照）。必ず新規コミットで追記する。
- 結果として**アーカイブファイル自体は Step 5.1 時点の HEAD を指し、その中の `report.json` は `archive_path: null`** となる。Step 6 のターミナル出力はワーキングツリーの `report.json` を読むので実害はない。

#### Step 5.4: アーカイブをスキップした場合

`status != "success"` の場合、アーカイブは作らず、代わりにターミナル (Step 6) で以下を明示する:

> ⚠️ アーカイブは status=success 時のみ作成されます。現在の status は `{status}` です。

### Step 6: Next Actions のターミナル出力

`/reimplement` の最後に、`reports/report.json` の `next_actions` 配列と `archive_path` をユーザー向けメッセージとしてターミナルに整形出力する。ユーザーはその場で次のアクションを選んで Claude Code に依頼できる。

**出力フォーマット:**

```
## Reproduction Complete

Status: {status}
Archive: {archive_path or "(not created; status != success)"}

## Next Actions

1. [HIGH] {action}
   理由: {reason}
   $ {command}

2. [MEDIUM] {action}
   理由: {reason}

3. [LOW] {action}
   ...
```

**原則:**
- ソースは `reports/report.json` の `next_actions` / `archive_path` / `status` を読み出すこと。ここで新規に生成・計算し直さない。
- `next_actions` が空なら Next Actions ブロックの代わりに "再現は完了しました。特筆すべき次のアクションはありません。" を出す。
- `command` が null の項目では `$ {command}` 行を省略する。
- `archive_path` が null の場合、代わりに理由（`status != success` など）を表示する。
- Phase 4 が完了し Step 5 のアーカイブも終わった**最後**に出力する。途中の Phase で出力しない。

---

## 核心原則

### Git 運用ルール（全 Phase 共通）

- **`git commit --amend` は全 Phase で禁止**。書き換え対象が最終コミットであっても、過去コミットであっても、例外なく使わない。履歴を破壊すると archive が参照している SHA / attempts.tsv に記録された SHA と実際のコミットがズレるため。修正を追加したくなったら必ず**新しいコミットを積む**（例: `chore: fix gitignore anchor for reports/samples/output`）。
- **`git reset --hard HEAD~1` は Experiment Loop の失敗復旧専用**。Phase 2/3 の試行が失敗した直後にのみ使う（`experiment-loop` スキル参照）。それ以外の文脈（コミット済みの過去作業を巻き戻す等）では禁止。
- **`git push --force` は禁止**。ローカル作業ブランチでも remote への強制 push は行わない。
- **`git commit` のたびに START_TIME / END_TIME を記録し、`reports/attempts.tsv` に 1 行追記する**（Phase 2/3 の Experiment Loop ルール。成功・失敗を問わず毎回実行）。
- **コミットメッセージは命令形**のシンプルな英語で 1 行目 72 文字以内（例: `attempt #3: bump libc to 2.31 for open3d`）。

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
