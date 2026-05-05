---
description: CV論文のGitHubリポジトリを全自動再現する。CWD=clone済みリポジトリで実行。
allowed-tools: Bash Read Write Edit Glob Grep Agent
---

# /reimplement — 論文リポジトリ全自動再現コマンド

CV 論文の GitHub リポジトリを Pixi 環境で全自動再現する。以下の Phase を順に実行する。

**NEVER STOP**: 人間に確認しない。Tier 分類に従い自律リトライ。手動停止のみで終了。

**REPORT_LANG**: 環境変数 `REPORT_LANG` で `report.html` / `report.json` 内のユーザー向け散文の出力言語を切り替える。`ja` (デフォルト) または `en`。値は `bootstrap.sh --lang` で渡され、Phase 4 で chrome 文字列の i18n 置換と、各種スキル (repo-analyzer の overview/problem、usage-documenter の description、sample-embedder の label、Phase 4 Step 1.7 の next_actions) が生成する散文の言語選択に使われる。論文・コード由来の固有名詞は翻訳しない。

---

## Phase 0: Initialize

### 成果物レイアウト（全 Phase 共通）

```
{repo_root}/
├── pixi.toml            # commit 対象
├── pixi.lock            # commit 対象
└── reports/
    ├── analysis.json    # Phase 1
    ├── attempts.tsv     # 全試行ログ（git 管理外）
    ├── environment.json # Phase 4 Step 1.4 実行環境スナップショット
    ├── report.json      # Phase 4 機械可読
    ├── report.html      # Phase 4 目視確認
    └── samples/         # Phase 4 入出力サンプル
        ├── input/
        └── output/

# リポジトリ外（Phase 4 Step 5、status=success のみ）
../{repo_name}-{short_sha}.tar.gz
```

### 初期化手順

1. `git status` で CWD が git リポジトリか確認
2. `git stash` で未コミット変更を退避（あれば）
3. `git remote -v` でリポジトリ名・URL を検出
4. `git submodule status` で submodule 確認
5. `mkdir -p reports`
6. `reports/attempts.tsv` をヘッダー行で初期化:
   ```
   attempt\tcommit\tphase\taction\tintent\tresult\terror_tier\terror_summary\tduration_s
   ```
7. `.gitignore` に `reports/attempts.tsv` と `reports/_baseline_sha` を追加
8. `git rev-parse HEAD > reports/_baseline_sha` で再現作業の起点 SHA を記録（Phase 4 Step 2 の duration 計算で `BASELINE_SHA..HEAD` の span を取るために使う。既存リポを clone した場合、`git log --reverse` の最古コミットがリポ作成時 = 数年前を指すため）
9. `ls` で依存ファイル一覧取得（Phase 1 事前情報）

### Pre-flight ガード（Phase 1 進入前に必ず通過）

ここで失敗したら attempt 番号を消費せずに直して再開（Tier 0）。省くと Phase 2 の attempt 1 が構造的に死ぬ。

```bash
# 1. git identity
git config user.email >/dev/null 2>&1 || git config user.email "claude@anthropic.com"
git config user.name  >/dev/null 2>&1 || git config user.name  "Claude"

# 2. キャッシュ書き込み権限
for d in "$HOME/.cache" /tmp; do [ -w "$d" ] || echo "WARN: $d not writable"; done
# .cache に書けない環境では env で逃がす:
#   export HF_HOME=/tmp/hf TORCH_HOME=/tmp/torch MPLCONFIGDIR=/tmp/mpl

# 3. ネットワーク到達
curl -sfm 5 -I https://pypi.org/simple/ >/dev/null || echo "WARN: pypi unreachable"
curl -sfm 5 -I https://huggingface.co       >/dev/null || echo "WARN: hf unreachable"

# 4. host libc（open3d 0.19+ は 2.31 以上必須）
ldd --version | head -1

# 5. CUDA↔PyTorch 互換（analysis.json 出力後に cross-check）
#    cuda_torch_compat_mismatch=true なら Phase 2 attempt 1 で推奨値で始める
```

---

## Phase 1: リポジトリ解析

**`repo-analyzer` スキル参照。** 結果を `reports/analysis.json` に出力。

### Feasibility Gate

`analysis.json.feasibility.status` で分岐:

- `infeasible` → Phase 2 に入らず Phase 4 へ直行。`report.json.status="failed"`、`errors=analysis.json.feasibility.blockers`、`next_actions` に代替手段（軽量版 / 別 weights / spec 要件）
- `degraded` → 警告記録の上 Phase 2 へ進む。`blockers` 内容で初手を変更:
  - `gpu_arch_incompatible`: attempt 1 から `recommended_torch/cuda` で pixi.toml を構成（`cuda_torch_compat_mismatch` と同フロー）
  - その他: OOM ladder を初手から縮小して開始
- `ok` → 通常進行

```json
{
  "repo_name": "string",
  "repo_url": "string",
  "github_slug": "string|null",
  "overview": {
    "title": "string|null",
    "tagline": "string|null",
    "paper_url": "string|null"
  },
  "problem": {
    "input": "string|null",
    "output": "string|null"
  },
  "coord_convention": {
    "world": "opencv|opengl|z_up|unknown",
    "evidence": "string|null"
  },
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
      "has_setup_py": "boolean",
      "has_cuda_extension": "boolean"
    }
  ],
  "dockerfile_search_note": "string|null",
  "cuda_torch_compat_mismatch": {
    "detected": "boolean",
    "recommended_cuda": "string|null",
    "recommended_torch": "string|null"
  },
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

**参照スキル**: `pixi-env-builder` / `dep-converter` / `cuda-dependency-resolver`。

`analysis.json.dep_type` に基づく変換戦略で pixi.toml を生成する。Type 別の詳細フロー・変換ルール・CUDA 設定は各スキルに定義。

### Experiment Loop

**`experiment-loop` スキル参照（NEVER STOP / Tier 分類 / TSV ログ）。**

```
while not succeeded:
  1. START_TIME=$(date +%s)                                     ← 省略禁止
  2. pixi.toml を生成/修正
  3. pixi install --dry-run                                     ← syntax/resolvability 事前チェック (Tier 0)
  4. git add pixi.toml && git commit -m "attempt #{n}: {action}"
  5. pixi install 2>&1 | tee build.log
  6. END_TIME=$(date +%s) && DURATION=$((END_TIME - START_TIME)) ← 省略禁止
  7. reports/attempts.tsv 追記                                   ← 成功・失敗問わず省略禁止
  8. 結果判定:
     成功 → 環境検証（torch.cuda.is_available()==True 必須、False は Tier 0）
     失敗 → experiment-loop の 4-Tier 分類
  9. 失敗時: git reset --hard HEAD~1
```

---

## Phase 3: 推論実行

**`experiment-loop` スキル参照。**

### Step 1: モデルダウンロード

`analysis.json.model_download` に基づく:

| method | 実行 |
|---|---|
| `wget` | `pixi run python -c "import urllib.request; ..."` / `wget` |
| `gdown` | `pixi run gdown {file_id} -O {output_path}` |
| `huggingface` | `pixi run python -c "from huggingface_hub import hf_hub_download; ..."` |
| `script` | README 記載のスクリプトを実行 |

**gdown --folder の二重ネスト問題**: `gdown --folder URL -O /workspace/weights/` → `/workspace/weights/weights/` になる。一時ディレクトリに DL → 中身を目的パスに移動。

**ダウンロード失敗**:
- URL 切れ → README 代替リンク、HuggingFace Hub 検索
- 認証必要 → Tier 3
- 容量過大 → 軽量版があれば代替

### Step 2: Headless GUI 対策

Docker 内は headless。`/etc/headless_patches/_headless_patch.py` を優先コピー/exec（cv2/open3d/matplotlib のモンキーパッチ）。無い場合のみ `experiment-loop` の「Headless 環境対策」テンプレから生成。

### Step 2.5: Telemetry 計測

推論時に取得し `reports/telemetry.json` に出力（Phase 4 が読む）:

```python
import time, torch, json
if torch.cuda.is_available():
    torch.cuda.reset_peak_memory_stats()
load_t0 = time.time()
model = ...  # モデルロード
load_t1 = time.time()
inf_t0 = time.time()
output = model(input)
inf_t1 = time.time()

# Telemetry honesty: model が実際に乗っているデバイスを参照する。
# torch.cuda.is_available() だと OOM ladder Step 5 の CPU fallback 後にも True のままで、
# device="<GPU 名>" を出力する silent false-success を生む。
on_gpu = next(model.parameters()).device.type == "cuda"
device = torch.cuda.get_device_name(0) if on_gpu else "cpu"
json.dump({
  "peak_vram_mb": int(torch.cuda.max_memory_allocated() / 1e6) if on_gpu else None,
  "model_load_time_s": round(load_t1 - load_t0, 2),
  "inference_fps": round(1.0 / (inf_t1 - inf_t0), 2) if (inf_t1 > inf_t0) else None,
  "device": device,
  "fallback_to_cpu": not on_gpu,
  "precision": str(next(model.parameters()).dtype) if hasattr(model, 'parameters') else None,
}, open("reports/telemetry.json", "w"), indent=2)
```

独自スクリプトでモデル変数を取れない場合は wrapper で `torch.cuda.max_memory_allocated()` と実行時間のみでも記録。

### Step 3: デモ/推論スクリプト実行（Experiment Loop）

```
while not inference_succeeded:
  1. START_TIME=$(date +%s)                                     ← 省略禁止
  2. スクリプト修正 or パラメータ変更
  3. git add -A && git commit -m "attempt #{n}: {action}"
  4. pixi run python {demo_command} 2>&1 | tee inference.log
  5. END_TIME=$(date +%s) && DURATION=$((END_TIME - START_TIME)) ← 省略禁止
  6. reports/attempts.tsv 追記                                   ← 省略禁止
  7. 結果判定:
     成功（出力ファイル生成）→ Phase 4
     失敗 → experiment-loop の 4-Tier:
       Tier 0: pre-flight 違反 → 修正、attempt 消費しない
       Tier 1: auto-fix（pypi add / DL 再試行 / headless patch）→ retry
       Tier 2-config: 設定変更で解決 → retry
       Tier 2-hardware: OOM ladder（Step 5 CPU fallback まで必ず）→ retry
       Tier 3: レポート記載 → Phase 4（status 判定ルール参照。推論が 1 件も成功していなければ failed）
  8. 失敗時: git reset --hard HEAD~1
```

---

## Phase 4: レポート生成

### Step 1: 中間ファイル削除

`cleaned.yml`（Type A2/A3）、`build.log` / `inference.log`（attempts.tsv に集約済み）、`_headless_patch.py`（Phase 3 で作成時）を削除。

### Step 1.4: 実行環境の記録

ホスト・OS・GPU・CUDA driver を `reports/environment.json` に保存し、Step 2 で `report.json.environment` に転記する。「どのマシンで再現したのか」「telemetry の数字をどの GPU 基準で読むか」を、レポートを開いた瞬間に判断できるようにする。

```python
import json, platform, socket, datetime, subprocess

def run(cmd):
    try:
        out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL).strip()
        return out or None
    except Exception:
        return None

def cpu_model():
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return None

def ram_gb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / 1024 / 1024, 1)
    except Exception:
        return None

gpus = []
nv = run("nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader,nounits")
if nv:
    for line in nv.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4 and parts[0].isdigit():
            gpus.append({
                "index": int(parts[0]),
                "name": parts[1],
                "memory_total_mb": int(parts[2]),
                "driver_version": parts[3],
            })

env = {
    "hostname": socket.gethostname(),
    "os": run("grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"'"),
    "kernel": platform.release(),
    "cpu": cpu_model(),
    "ram_total_gb": ram_gb(),
    "gpus": gpus,
    "cuda_version": run("nvidia-smi --query | grep -m1 'CUDA Version' | awk '{print $4}'"),
    "python_version": platform.python_version(),
    "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
}
with open("reports/environment.json", "w") as f:
    json.dump(env, f, indent=2)
```

取得不可なフィールドは `null`。GPU 不在環境では `gpus=[]`、`cuda_version=null`。

### Step 1.5: 使い方情報の抽出

**`usage-documenter` スキル参照。** 3 段階（Quickstart / Advanced / Developer）で `usage` オブジェクトを生成し、Step 2 で `report.json` に組み込む。

### Step 1.6: 入出力サンプルの抽出

**`sample-embedder` スキル参照。** Phase 3 の成功コマンドから入出力ファイルを特定し、`reports/samples/` に正規化コピーして `samples` オブジェクトを生成する。

### Step 1.7: Next Actions の生成

再現作業後のユーザーアクションを `next_actions` 配列として生成。Step 2 で `report.json` に組み込み、Step 3 で `report.html` にレンダリング、Step 6 でターミナル出力（3 箇所で同一ソース）。

**status 別の生成規則**:

- **success**（典型 2–4 件）:
  - 検証済み quickstart コマンドを自分のデータで試す（`usage.quickstart.command` を `command` に転記）
  - `usage.advanced` の未検証項目を動かす
  - `samples` の出力を別入力で再生成
  - ベンチマーク・評価スクリプトがあれば実行

- **partial**（典型 3–5 件、high/medium 中心）:
  - 未達 Phase の特定と指示
  - `errors` 解消の具体手順（ファイル名・コマンド付き）
  - 軽量パラメータで先に動作確認

- **failed**（典型 3–6 件、high 中心）:
  - 失敗 Tier に応じた根本原因と次のデバッグ手順
  - 代替アプローチ（別チャンネル、別バージョン、Docker fallback）
  - `errors` 各項目の修正候補
  - `gpu_arch_incompatible` が `errors` に含まれる場合は高優先度で必ず記す:
    - `action`: 推奨 torch+cuda への更新手順（`recommended_torch/cuda` 使用）
    - `reason`: ホスト GPU アーキテクチャと必要バージョンの具体的説明
    - `command`: pixi.toml の torch wheel 行の書き換え例（依存再ビルド手順も含める）
    - `cost`: 再ビルドのみなら `free`、API 非互換で移植必要なら effort `high`

**スキーマ**:

```json
[
  {
    "priority": "high|medium|low",
    "effort": "low|medium|high",
    "cost": "free|gpu_upgrade|paid_api|external_data",
    "action": "string",
    "reason": "string",
    "command": "string|null"
  }
]
```

**原則**:
- 各項目は独立実行可能にする（前後依存が強い場合は 1 項目にまとめる）
- `action` は具体的に書く（×「環境を修正する」／○「`pixi add --pypi xformers==0.0.23` を追加してリビルド」）
- 結果が無くても最低 1 件は出す（success でも「自分のデータで試す」等）
- **priority と cost を混同しない**: "24GB GPU で full-res" は `cost=gpu_upgrade` なので現手元で実行不可 → `high` ではない。**今動かせるタスクを `high` に置く**
- `high` は 0–2 件
- `action` / `reason` は `$REPORT_LANG` (`ja` デフォルト / `en`) に従って書く。`command` フィールドはコマンド原文のまま（翻訳しない）

### Step 1.7.5: 失敗の主因サマリ (failure_headline / failure_recoverability)

**`status` が `success` のときはスキップ** (両フィールド `null`)。`failed` / `partial` / Phase 1 `infeasible` のときのみ生成し、サマリーカードに 1 行で表示する。`errors[]` 配列を全部読まなくても **「いま直せるのか / GPU を買うべきなのか / 諦めるべきなのか」** がレポートを開いた瞬間に判断できるようにする。

#### `failure_headline`

`errors[]` の中で **最も上流のブロッカー** (これを直さないと他のエラーが解決しても先に進まないもの) を 1 つ選び、**1-2 文 (最大 120 字、改行禁止)** で圧縮する。`$REPORT_LANG` (`ja` デフォルト / `en`) に従う。固有名詞・パッケージ名・ファイル名は原文ママ。

良い例 (ja):
- `"非公開ライブラリ animatrix が PyPI / GitHub のいずれにも存在せず、すべての推論スクリプトが import 段階で停止する。"`
- `"NVIDIA A100 80GB でも GPU OOM が発生し、Step 5 (CPU fallback) でも RAM 不足で SIGKILL される。"`
- `"setup.sh 23 行目に if [-d ] の構文エラーがあり、依存インストールが完走しない。"`

悪い例:
- 全部書く: `"animatrix が無く、setup.sh も壊れていて、データセットも公開されていない..."` (列挙は `errors[]` の役割)
- 抽象的: `"環境構築が失敗した"` (ステータスバッジで既に分かる)
- 解決策を含む: `"animatrix の代替を探す必要がある"` (それは `next_actions` の役割)

#### `failure_recoverability`

3 値 enum。次の優先順位で判定 (上から順、最初にマッチしたものを採用):

| 値 | 判定基準 | バッジ色 |
|---|---|---|
| `blocked` | 非公開リソース / 認証必須 / 著者対応待ちで自力では解決不能。`errors[]` に `missing_private_*`, `missing_internal_*`, `no_public_*`, `needs_auth`, `private_repo`, `explicit_unofficial_warning`, `license_restricted`, `paywall` のいずれかを含む。または `next_actions[].cost` が `external_data` / `paid_api` 中心 | 赤 (= var(--failed)) |
| `hardware` | GPU / CPU / RAM / disk のスペック不足 (= 強い PC を用意すれば動く)。`errors[]` に `OOM`, `no kernel image`, `gpu_arch_incompatible` (Step 4 まで失敗), `disk_full`, `vram_insufficient` のいずれかを含み、上記 `blocked` に該当しない | 橙 (= var(--partial)) |
| `fixable` | 設定 / コード / 依存バージョンの修正で動く可能性が高い。`broken_setup_script`, `syntax_error`, `version_mismatch`, `module_not_found`, `config_typo`, `compile_failure` 等。または **Tier 0 / Tier 1 / Tier 2-config 範囲** に分類されるエラーが主因 | 黄 (= var(--success)) |

**MUST**: `errors[]` が空でも `status != success` なら何かしら判定する (例: Phase 2 が pixi install で SegFault した未分類ケースは `fixable` をデフォルト)。

判定ロジックは Claude が `errors[]` と `attempts.tsv` から推論する (機械的ヒューリスティクスではなく文脈判断)。

### Step 1.8: 関連 GitHub Issue / PR の集約検索

`status` が `failed` / `partial` / `infeasible` のときに限り、`analysis.json.github_slug` (Phase 1 で `repo_url` から導出) を使って同リポジトリの Issue / PR を gh で引き、**「同じ症状を踏んだ人がいないか」**を `report.json.related_issues` と `report.html` の新セクションに反映する。`success` 時はスキップ。

クエリセット (重複除去のうえ最大 8 件、各 6 単語以下に正規化):
1. `report.json.errors[]` の各文字列の**先頭 6 単語**（一番質の高い検索キー。例: `"missing_private_dependency animatrix utils.common"`）
2. `attempts.tsv` の `result=failed` 行の `error_summary` 列の**先頭 6 単語**
3. `next_actions[].action` の名詞句から抽出したトピック語（例: `TripoSG checkpoints`, `setup.sh syntax`）

実行:

```bash
QUERIES=(); for q in "${ERROR_SUMMARIES[@]}" "${ATTEMPT_ERRS[@]}" "${TOPIC_TERMS[@]}"; do
  QUERIES+=(--query "$q")
done
GITHUB_SLUG=$(jq -r '.github_slug // empty' reports/analysis.json)
if [ -n "$GITHUB_SLUG" ]; then
  bash /paper-reproduce-skills/scripts/search_github_issues.sh \
    --repo "$GITHUB_SLUG" --kind both --limit 3 \
    "${QUERIES[@]}" \
    --output reports/_gh_aggregate.json
  python3 /paper-reproduce-skills/scripts/build_related_issues_block.py \
    --input reports/_gh_aggregate.json \
    --i18n /paper-reproduce-skills/templates/i18n.json \
    --lang "${REPORT_LANG:-ja}" \
    --max 10 \
    --output reports/_related_issues_block.html
fi
```

`reports/_gh_aggregate.json.results[]` の上位 10 件を `report.json.related_issues` に転記する。`gh` 未インストール / 未認証 / rate-limit / マッチ 0 件のいずれの場合も中間 JSON は空配列 `{"results": []}` で生成され、ビルダは `<p class="usage-empty">{empty_related_issues}</p>` を返すため Phase 4 全体は決して止まらない。

中間ファイル `_gh_aggregate.json` / `_related_issues_block.html` は Step 1 の中間ファイル削除で消す対象 (Step 3 で読み終わったあと)。

### Step 2: reports/report.json 生成（機械可読、SSOT）

```json
{
  "repo_name": "string",
  "repo_url": "string",
  "overview": {
    "title": "string|null",
    "tagline": "string|null",
    "paper_url": "string|null"
  },
  "problem": {
    "input": "string|null",
    "output": "string|null"
  },
  "status": "success|partial|failed",
  "failure_headline": "string|null",
  "failure_recoverability": "fixable|hardware|blocked|null",
  "dep_type": "string",
  "dep_type_label": "string",
  "total_attempts": "number",
  "duration_total_s": "number",
  "pixi_toml_hash": "string",
  "inference_output": "string|null",
  "errors": ["string"],
  "environment": {
    "hostname": "string|null",
    "os": "string|null",
    "kernel": "string|null",
    "cpu": "string|null",
    "ram_total_gb": "number|null",
    "gpus": [
      {
        "index": "number",
        "name": "string",
        "memory_total_mb": "number",
        "driver_version": "string|null"
      }
    ],
    "cuda_version": "string|null",
    "python_version": "string|null",
    "timestamp": "string"
  },
  "telemetry": {
    "peak_vram_mb": "number|null",
    "model_load_time_s": "number|null",
    "inference_fps": "number|null",
    "device": "string|null",
    "fallback_to_cpu": "boolean|null",
    "precision": "string|null"
  },
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
      "effort": "low|medium|high",
      "cost": "free|gpu_upgrade|paid_api|external_data",
      "action": "string",
      "reason": "string",
      "command": "string|null"
    }
  ],
  "related_issues": [
    {
      "kind": "issue|pr",
      "number": "number",
      "title": "string",
      "url": "string",
      "state": "open|closed",
      "updated_at": "string",
      "matched_query": "string"
    }
  ],
  "archive_path": "string|null",
  "plugin_version": "1.0.0"
}
```

**埋め込み規則**:
- `overview` → `analysis.json.overview` をそのまま転記。各フィールドは `null` 許容
- `problem` → `analysis.json.problem` をそのまま転記。各フィールドは `null` 許容
- `environment` → Step 1.4 の `reports/environment.json` をそのまま転記
- `usage` → Step 1.5 の結果をそのまま。取れなかった階層は `null`（`advanced` のみ空配列 `[]`）
- `samples` → Step 1.6 の結果をそのまま。パスは `reports/` 相対（例: `samples/input/left.png`）
- `next_actions` → Step 1.7 の結果をそのまま。`report.html` とターミナル出力はここから読む
- `failure_headline` / `failure_recoverability` → Step 1.7.5 の結果。`success` 時は両方 `null`
- `related_issues` → Step 1.8 の `_gh_aggregate.json.results[]` 上位 10 件をそのまま転記。`success` 時 / Step 1.8 スキップ時 / マッチ 0 件は空配列 `[]`
- `archive_path` → Step 5 で生成されるアーカイブパス（親ディレクトリからの絶対）。Step 2 時点は `null` 仮置き、Step 5 成功時のみ更新

**status 判定**（上から順、最初にマッチしたものを採用）:
- `failed`:
  - Phase 1 で `infeasible`
  - `pixi install` が最終的に失敗
  - Tier 3 到達 + `phase3 run_inference` 行が全て `result=failed`
  - 推論成功ゼロ件で全 attempt 消化
- `partial`: pixi install 成功 + 推論 1 件以上成功 + 一部未達
- `success`: pixi install 成功 + quickstart 推論が全成功

**MUST NOT**: Tier 3 到達時の `partial` へのデフォルト落とし。

**TSV 値検証**（Step 2 開始時に必須）: `attempts.tsv` の各列が `experiment-loop/SKILL.md` の正規形に従っているか確認、違反があれば `report.json` 生成前に修正。

```bash
# phase: phase0–phase4
awk -F'\t' 'NR>1 && $3 !~ /^phase[0-4]$/ {print "INVALID phase row "NR": "$3}' reports/attempts.tsv
# result: success / failed / crashed / timed_out
awk -F'\t' 'NR>1 && $6 !~ /^(success|failed|crashed|timed_out)$/ {print "INVALID result row "NR": "$6}' reports/attempts.tsv
# error_tier: tier0 / tier1 / tier2-config / tier2-hardware / tier3 / -
awk -F'\t' 'NR>1 && $7 !~ /^(tier[013]|tier2-(config|hardware)|-)$/ {print "INVALID tier row "NR": "$7}' reports/attempts.tsv
```

検出時は `sed -i` で正規形に置換（例: `fail`→`failed`、`crash`→`crashed`、`timeout`→`timed_out`、`1`→`tier1`、`T1`→`tier1`、`Tier 1`→`tier1`、`2`→`phase2`）。違反ゼロ確認後に次の手順へ。

**duration_total_s** の算出（過小見積もり防止のクロスチェック必須）:

```bash
SUM=$(awk -F'\t' 'NR>1 {s+=$9} END {print s+0}' reports/attempts.tsv)

# Phase 0 で記録した baseline SHA 以降のコミットだけを span 計算に使う。
# 既存リポを再現対象にすると git log --reverse がリポ作成時 (数年前) を返すため、
# BASELINE_SHA..HEAD で再現作業中のコミットだけに範囲を絞る。
BASELINE_SHA=$(cat reports/_baseline_sha 2>/dev/null || echo "")
if [ -n "$BASELINE_SHA" ] && git merge-base --is-ancestor "$BASELINE_SHA" HEAD 2>/dev/null; then
    FIRST=$(git log --format='%at' --reverse "${BASELINE_SHA}..HEAD" | head -1)
    LAST=$(git log --format='%at' | head -1)
    SPAN=$((LAST - ${FIRST:-$LAST}))
else
    # baseline 不明 (古い再現セッション / 後付け実行) なら SPAN は 0 として SUM のみ採用
    SPAN=0
fi

# 大きい方を採用。計測漏れで合算が過小でも git タイムスタンプが下限を保証
DURATION_TOTAL=$(( SUM > SPAN ? SUM : SPAN ))
```

`SUM < SPAN * 0.7` の場合は計測漏れの兆候。`note` に「duration_s 一部欠落」記載可、ただし `duration_total_s` は必ず大きい方（`SPAN`）を採用。

### Step 3: reports/report.html 生成（目視確認）

**`templates/report.html` をそのままコピーし、`{{...}}` プレースホルダーのみ置換する。** HTML/CSS を書き直さない。

```bash
cp /paper-reproduce-skills/templates/report.html reports/report.html
cp /paper-reproduce-skills/templates/view.sh     reports/view.sh
chmod +x reports/view.sh
```

#### 言語解決と i18n strings dict のロード

```bash
LANG_CODE="${REPORT_LANG:-ja}"
case "$LANG_CODE" in ja|en) ;; *) LANG_CODE=ja ;; esac
```

`/paper-reproduce-skills/templates/i18n.json` の `$LANG_CODE` キーが strings dict。`{{T_*}}` 系プレースホルダはこの dict から、`{{HTML_LANG}}` は `dict.html_lang` から、`{{I18N_JSON_INLINE}}` は dict 全体を JSON.stringify した文字列から置換する。

```bash
python3 - <<'PY' > /tmp/i18n_subst.json
import json, os
lang = os.environ.get('REPORT_LANG', 'ja')
if lang not in ('ja', 'en'):
    lang = 'ja'
with open('/paper-reproduce-skills/templates/i18n.json') as f:
    d = json.load(f)[lang]
print(json.dumps({'lang': lang, 'dict': d}))
PY
```

`{{T_*}}` キー名は dict キーを大文字化したもの (例: `dict.h2_summary` → `{{T_H2_SUMMARY}}`、`dict.copy_idle` → `{{T_COPY_IDLE}}` ※ JS 側で参照する copy_* / viewer_* / fig_* / note_* は `{{I18N_JSON_INLINE}}` 経由で window.__I18N__ に注入されるため、template 側で `{{T_*}}` 個別置換は不要)。詳細は下記プレースホルダー表を参照。

**MUST NOT**:
- `<style>` 内を変更する
- プレースホルダー名を追加・削除する
- 新セクション (`<h2>`, `<div>`) を追加する
- `<html lang="…">` / `<title>…</title>` を i18n 以外の理由で書き換える（言語切替は `{{HTML_LANG}}` / `{{T_TITLE_PREFIX}}` 経由のみ）

置換後の先頭 6 行は (LANG_CODE=ja の場合):

```
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>再現レポート: {REPO_NAME}</title>
```

`view.sh` は `python3 -m http.server` で `report.html` を開くヘルパ（3D ビューワの CORS 対策）。

**ASSERTION**: `report.html` の `<tr>` 行数 == `attempts.tsv` のデータ行数。

#### プレースホルダー置換

**Content placeholders（動的データ由来）**:

| プレースホルダー | 値の取得元 |
|---|---|
| `{{REPO_NAME}}` | `analysis.json.repo_name` |
| `{{REPO_URL}}` | `analysis.json.repo_url` |
| `{{TIMESTAMP}}` | 現在日時（形式: `YYYY-MM-DD HH:MM:SS ±HH:MM`） |
| `{{OVERVIEW_BLOCK}}` | `report.json.overview` をレンダリング |
| `{{PROBLEM_BLOCK}}` | `report.json.problem` をレンダリング |
| `{{ENVIRONMENT_BLOCK}}` | `report.json.environment` をレンダリング |
| `{{STATUS}}` | `report.json.status` |
| `{{FAILURE_HEADLINE}}` | `report.json.failure_headline` (HTML エスケープ済み)。`null` のときはサマリーカードのセルごと非表示 (Mustache `{{#FAILURE_HEADLINE}}...{{/FAILURE_HEADLINE}}` で囲む) |
| `{{FAILURE_RECOVERABILITY}}` | `report.json.failure_recoverability` の値そのまま (`fixable` / `hardware` / `blocked`)。CSS class `recoverability-{value}` で色分けされる |
| `{{T_RECOVERABILITY_LABEL}}` | `recoverability_*` 文字列。値ごとに `recoverability_fixable` / `recoverability_hardware` / `recoverability_blocked` のいずれかを `i18n.json[$LANG_CODE]` から引き、置換する |
| `{{DEP_TYPE}}` | `analysis.json.dep_type` + `dep_type_label` |
| `{{TOTAL_ATTEMPTS}}` | `attempts.tsv` のデータ行数 |
| `{{DURATION_TOTAL}}` | `report.json.duration_total_s` を `Hh Mm Ss` 形式に整形（例: "2m 34s" / "1h 11m 5s"） |
| `{{ATTEMPTS_ROWS}}` | `attempts.tsv` 各行を `<tr class="result-{result}">` 化（9 列、TSV と同形・同順）。`result-*` class は Result 列の色付けに使用 |
| `{{ARTIFACTS_LIST}}` | 生成物の `<li>` リスト |
| `{{ARCHIVE_PATH}}` | `report.json.archive_path` (HTML エスケープ済み)。`null` のとき (= Phase 1 infeasible で Step 5.2 まで進まなかったケース) は Mustache `{{#ARCHIVE_PATH}}...{{/ARCHIVE_PATH}}` で行ごと非表示 |
| `{{QUICKSTART_BLOCK}}` | `usage.quickstart` をレンダリング |
| `{{ADVANCED_BLOCK}}` | `usage.advanced` をレンダリング |
| `{{DEVELOPER_BLOCK}}` | `usage.developer` をレンダリング |
| `{{SAMPLES_BLOCK}}` | `samples.items` をレンダリング |
| `{{NEXT_ACTIONS_BLOCK}}` | `next_actions` をレンダリング |
| `{{PIXI_TOML_CONTENT}}` | pixi.toml の内容（HTML エスケープ済み） |
| `{{ERRORS_LIST}}` | エラーの `<li>` リスト（`failed`/`partial` 時のみ） |
| `{{RELATED_ISSUES_BLOCK}}` | Step 1.8 で生成した `reports/_related_issues_block.html` をそのまま挿入（`failed`/`partial`/`infeasible` 時のみ） |
| `{{PLUGIN_VERSION}}` | `plugin.json.version` |

**i18n placeholders と各ブロックの HTML レンダリング規則**: [`templates/RENDERING.md`](../templates/RENDERING.md) を参照。

このファイルには以下が集約されている (本セクションでは概略のみ):
- `{{HTML_LANG}}` / `{{T_TITLE_PREFIX}}` / `{{T_H2_*}}` / `{{T_H3_*}}` / `{{T_LABEL_*}}` / `{{T_TH_*}}` / `{{T_LEGEND_*}}` / `{{T_WARN_*}}` / `{{T_FOOTER_*}}` / `{{I18N_JSON_INLINE}}` の dict キー対応表
- `OVERVIEW_BLOCK` / `PROBLEM_BLOCK` / `ENVIRONMENT_BLOCK` / `QUICKSTART/ADVANCED/DEVELOPER_BLOCK` / `SAMPLES_BLOCK` (image_pair / image_triple / gaussian_splat / point_cloud / mesh / video) / `NEXT_ACTIONS_BLOCK` の HTML 雛形
- 各ブロックの空状態フォールバック (`empty_*` メッセージ)
- 動的レンダリング時に追加で参照する dict キー (`label_*` / `empty_*` / `verified_badge` / `source_label` / `fig_*` / `note_*` / `related_issue_*`)
- HTML エスケープ規則 (`<` `>` `&` `"` `'`)


### Step 3.5: report.html の最終ゲート (finalize_report.py)

Step 3 で i18n 置換と Mustache 風 `{{#X}}...{{/X}}` 条件ブロック展開を Claude が手動で行うため、置換漏れが発生し得る (実例: 旧版で `{{T_H2_ERRORS}}` がそのまま出力された事案)。**このステップは必ず実行する**。

```bash
LANG_CODE="${REPORT_LANG:-ja}"
case "$LANG_CODE" in ja|en) ;; *) LANG_CODE=ja ;; esac

# 条件ブロックは status / 値の有無に応じて有効化
FLAG_ARGS=()
STATUS=$(jq -r '.status' reports/report.json)
HEADLINE=$(jq -r '.failure_headline // empty' reports/report.json)
ARCHIVE=$(jq -r '.archive_path // empty' reports/report.json)
case "$STATUS" in
  failed|partial)   FLAG_ARGS+=(--flag ERRORS) ;;
esac
if [ -n "$HEADLINE" ]; then
  # サマリーカードに 1 行原因サマリ + recoverability バッジを表示
  FLAG_ARGS+=(--flag FAILURE_HEADLINE)
fi
if [ -n "$ARCHIVE" ]; then
  # Artifacts セクションに 📦 アーカイブパスの行を表示
  FLAG_ARGS+=(--flag ARCHIVE_PATH)
fi
case "$STATUS" in
  failed|partial|infeasible)
    # related_issues が 1 件以上、または gh スキップでも empty メッセージを表示するため
    # 集約を実行したケース (status != success) では常に有効化
    FLAG_ARGS+=(--flag RELATED_ISSUES)
    ;;
esac

python3 /paper-reproduce-skills/scripts/finalize_report.py \
  --input reports/report.html \
  --i18n /paper-reproduce-skills/templates/i18n.json \
  --lang "$LANG_CODE" \
  "${FLAG_ARGS[@]}"
```

`finalize_report.py` の責務:
1. `{{#FLAG}}...{{/FLAG}}` を `--flag` 指定通りに開閉処理 (未指定はブロック削除)
2. 残った `{{T_*}}` を `i18n.json[lang]` から再 lookup して置換 (Step 3 の取りこぼしを救う)
3. `{{I18N_JSON_INLINE}}` を未置換のままにしない (空辞書 `{}` で fallback)
4. それでも残った未置換は **該当 H2 セクション / H3 行 / legend 行を非表示化**

**ASSERTION**: 完了後に `grep -c '{{[A-Z]' reports/report.html` が **0** であること。

### Step 4: 成果物確認

Phase 0 の「成果物レイアウト」通りに全ファイルが揃っているか確認。

### Step 5: 最終コミットとアーカイブ

**5.1 レポート類を 1 コミット + tracked 確認:**
```bash
git status --porcelain
git add reports/ pixi.toml pixi.lock
git commit -m "chore: finalize reproduction reports"

# 全 sample パスが git に乗ったか検証 (.gitignore 衝突 / symlink 切れの早期検出)。
# git archive HEAD は追跡ファイルしか含めないため、ここで漏れていると Step 5.2 のアーカイブに穴が空く。
# process substitution で while を親シェルで実行 (subshell の exit が無効化されるのを回避)。
while IFS= read -r path; do
    [ -z "$path" ] && continue
    full="reports/$path"
    if [ -L "$full" ]; then
        echo "FAIL: $full is a symlink (git archive で dangling link を配布する危険)" >&2
        echo "FIX: cp -L で実体コピーに置換、または symlink 削除して再 add" >&2
        exit 1
    fi
    git ls-files --error-unmatch -- "$full" >/dev/null 2>&1 || {
        echo "FAIL: $full not tracked (.gitignore 衝突の可能性)" >&2
        echo "FIX: .gitignore に negation rule 追記 (例: '!reports/samples/output/*.ply')" >&2
        echo "     その後: git add -f \"$full\" && git commit -m 'fix: include sample $path'" >&2
        exit 1
    }
done < <(jq -r '.samples.items[]? | .input_paths[]?, .output_paths[]?' reports/report.json)
```
`reports/attempts.tsv` と `reports/_baseline_sha` は Phase 0 で `.gitignore` 追加済みなので `git add reports/` には載らない。`reports/` 配下に新規ファイルが無ければ空コミットを skip する。

**5.2 アーカイブ作成**（`status == success | partial | failed` のいずれでも生成。Phase 1 で `infeasible` 判定により Step 5.1 を実行できなかったときのみ skip → `archive_path=null`）:
```bash
REPO_NAME=$(basename "$PWD")
SHORT_SHA=$(git rev-parse --short HEAD)
ARCHIVE_PATH="$(cd .. && pwd)/${REPO_NAME}-${SHORT_SHA}.tar.gz"
git archive --format=tar.gz --prefix="${REPO_NAME}-${SHORT_SHA}/" HEAD -o "${ARCHIVE_PATH}"
```
`git archive HEAD` は追跡ファイルのみ（attempts.tsv / .pixi / モデル重みは含まない）。親ディレクトリに書けない場合は `/tmp/${REPO_NAME}-${SHORT_SHA}.tar.gz` にフォールバック。

**partial / failed でも作る理由**: 後で別マシンで再開するときの起点 (修正済み pixi.toml, スクリプトパッチ, レポート一式) が一括で持ち運べる。`git archive HEAD` の生成は数秒・数十 MB で完了するためコストも低い。

**5.3 `report.json.archive_path` 更新**（新規コミット、amend 禁止）:
```bash
git add reports/report.json && git commit -m "chore: record archive path"
```
アーカイブ内部の `report.json.archive_path` は `null` のままだがワーキングツリー側は最新なので Step 6 の出力に実害なし。

### Step 6: Next Actions のターミナル出力

`report.json` の `next_actions` / `archive_path` / `status` を読み、そのまま出力する（再生成・再計算しない）。見出し・固定文言は `$REPORT_LANG` に従う。`action` / `reason` は既に Step 1.7 で `$REPORT_LANG` で書かれている前提で再翻訳しない。

LANG=ja（デフォルト）:

```
## 再現完了

ステータス: {status}
アーカイブ: {archive_path or "(infeasible のため未作成)"}

## 次のアクション

1. [HIGH] {action}
   理由: {reason}
   $ {command}

2. [MEDIUM] {action}
   理由: {reason}

3. [LOW] {action}
   ...
```

LANG=en:

```
## Reproduction Complete

Status: {status}
Archive: {archive_path or "(not created; Phase 1 infeasible)"}

## Next Actions

1. [HIGH] {action}
   Reason: {reason}
   $ {command}
...
```

- `next_actions` が空 → ja: 「再現は完了しました。特筆すべき次のアクションはありません。」 / en: "Reproduction complete. No notable next actions."
- `command` が null の項目は `$ {command}` 行を省略
- `archive_path` が null なら代わりに理由を表示
- 出力タイミングは Step 5 完了後の最後のみ

---

## 核心原則

### Git 運用ルール（全 Phase 共通）

- `git commit --amend` は全 Phase で禁止（archive SHA と attempts.tsv の SHA ズレを避ける）
- `git reset --hard HEAD~1` は Experiment Loop の失敗復旧専用（`experiment-loop` 参照）
- `git push --force` 禁止
- 各 `git commit` ごとに START_TIME/END_TIME を測り `attempts.tsv` に 1 行追記（成否問わず）
- コミットメッセージは命令形・英語・72 文字以内（例: `attempt #3: bump libc to 2.31 for open3d`）

### NEVER STOP

失敗しても止まらない。Tier 分類に従い自律的に修正・再試行。停止条件は全 Phase 完了または手動停止のみ。

### 依存関係の原則

`pixi-env-builder` / `cuda-dependency-resolver` / `dep-converter` に委譲。Divide-and-Conquer、no-build-isolation、チャンネル順、CUDA 統一はそれらのスキル内で定義。ここでは重複して書かない。
