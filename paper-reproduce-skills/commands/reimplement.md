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
| `{{DEP_TYPE}}` | `analysis.json.dep_type` + `dep_type_label` |
| `{{TOTAL_ATTEMPTS}}` | `attempts.tsv` のデータ行数 |
| `{{DURATION_TOTAL}}` | `report.json.duration_total_s` を `Hh Mm Ss` 形式に整形（例: "2m 34s" / "1h 11m 5s"） |
| `{{ATTEMPTS_ROWS}}` | `attempts.tsv` 各行を `<tr class="result-{result}">` 化（9 列、TSV と同形・同順）。`result-*` class は Result 列の色付けに使用 |
| `{{ARTIFACTS_LIST}}` | 生成物の `<li>` リスト |
| `{{QUICKSTART_BLOCK}}` | `usage.quickstart` をレンダリング |
| `{{ADVANCED_BLOCK}}` | `usage.advanced` をレンダリング |
| `{{DEVELOPER_BLOCK}}` | `usage.developer` をレンダリング |
| `{{SAMPLES_BLOCK}}` | `samples.items` をレンダリング |
| `{{NEXT_ACTIONS_BLOCK}}` | `next_actions` をレンダリング |
| `{{PIXI_TOML_CONTENT}}` | pixi.toml の内容（HTML エスケープ済み） |
| `{{ERRORS_LIST}}` | エラーの `<li>` リスト（`failed`/`partial` 時のみ） |
| `{{PLUGIN_VERSION}}` | `plugin.json.version` |

**i18n placeholders（chrome 文字列、`i18n.json[$LANG_CODE]` 由来）**:

| プレースホルダー | dict キー |
|---|---|
| `{{HTML_LANG}}` | `html_lang` |
| `{{T_TITLE_PREFIX}}` | `title_prefix` |
| `{{T_META_GENERATED}}` | `meta_generated` |
| `{{T_H2_SUMMARY}}` / `{{T_H2_ENVIRONMENT}}` / `{{T_H2_OVERVIEW}}` / `{{T_H2_PROBLEM}}` / `{{T_H2_USAGE}}` / `{{T_H2_NEXT_ACTIONS}}` / `{{T_H2_SAMPLES}}` / `{{T_H2_ATTEMPTS}}` / `{{T_H2_ARTIFACTS}}` / `{{T_H2_PIXI}}` / `{{T_H2_ERRORS}}` | `h2_*` |
| `{{T_H3_QUICKSTART}}` / `{{T_H3_ADVANCED}}` / `{{T_H3_DEVELOPER}}` | `h3_*` |
| `{{T_LABEL_STATUS}}` / `{{T_LABEL_DEP_TYPE}}` / `{{T_LABEL_TOTAL_ATTEMPTS}}` / `{{T_LABEL_TOTAL_DURATION}}` | `label_*` |
| `{{T_TH_NUM}}` / `{{T_TH_COMMIT}}` / `{{T_TH_PHASE}}` / `{{T_TH_ACTION}}` / `{{T_TH_INTENT}}` / `{{T_TH_RESULT}}` / `{{T_TH_TIER}}` / `{{T_TH_ERROR_SUMMARY}}` / `{{T_TH_DURATION_S}}` | `th_*` |
| `{{T_LEGEND_SUMMARY}}` / `{{T_LEGEND_PHASE_HEADING}}` / `{{T_LEGEND_TIER_HEADING}}` / `{{T_LEGEND_PHASE0_DESC}}` … `{{T_LEGEND_PHASE4_DESC}}` / `{{T_LEGEND_TIER0_DESC}}` / `{{T_LEGEND_TIER1_DESC}}` / `{{T_LEGEND_TIER2_CONFIG_DESC}}` / `{{T_LEGEND_TIER2_HARDWARE_DESC}}` / `{{T_LEGEND_TIER3_DESC}}` / `{{T_LEGEND_DASH_DESC}}` | `legend_*` |
| `{{T_WARN_FILE_PROTOCOL_TITLE}}` / `{{T_WARN_FILE_PROTOCOL_BODY}}` | `warn_file_protocol_*` |
| `{{T_FOOTER_GENERATED_BY}}` | `footer_generated_by`（`{plugin_name}` を `paper-reproduce` に、`{version}` を `plugin.json.version` に展開してから挿入） |
| `{{I18N_JSON_INLINE}}` | strings dict 全体を `JSON.stringify` 相当（`<` `>` `&` をエスケープ済み）。JS 側 (copy ボタン、3D viewer エラー、Point size スライダ) はこれを `window.__I18N__` 経由で読む |

**動的レンダリング側で使う dict キー**（OVERVIEW/PROBLEM/ENVIRONMENT/USAGE/SAMPLES の中で生成する HTML フラグメントに埋め込む）:

| 用途 | dict キー |
|---|---|
| 環境カードのラベル | `label_hostname` / `label_os` / `label_cpu` / `label_ram` / `label_gpu` / `label_cuda_driver` / `label_python` |
| 問題設定のラベル | `label_input` / `label_output` |
| 空状態メッセージ | `empty_overview` / `empty_problem` / `empty_environment` / `empty_quickstart` / `empty_advanced` / `empty_developer` / `empty_samples` / `empty_next_actions` |
| Quickstart の Verified バッジ | `verified_badge` |
| Advanced の Source 接頭辞 | `source_label` |
| Sample I/O の figcaption | `fig_input` / `fig_output` / `fig_left` / `fig_right` / `fig_disparity` |
| Sample I/O のメタノート接頭辞 | `note_gaussians` / `note_points` / `note_format` |

#### overview ブロックのレンダリング

**`{{OVERVIEW_BLOCK}}`**:

```html
<!-- title が非 null の場合のみ -->
<h3 class="overview-title">{title}</h3>
<!-- tagline が非 null の場合のみ -->
<p class="overview-tagline">{tagline}</p>
<!-- paper_url が非 null の場合のみ -->
<p class="overview-link"><a href="{paper_url}">{paper_url}</a></p>
```

3 フィールド全て `null` の場合: `<p class="usage-empty">{dict.empty_overview}</p>`

#### problem ブロックのレンダリング

**`{{PROBLEM_BLOCK}}`** — 各 `summary-item` を順に並べる。label は `dict.label_input` / `dict.label_output`:

| label | value（null は `—`） |
|---|---|
| `dict.label_input` | `{input}` |
| `dict.label_output` | `{output}` |

```html
<div class="summary-grid">
  <div class="summary-item"><label>{dict.label_input}</label><span class="value">{input}</span></div>
  <div class="summary-item"><label>{dict.label_output}</label><span class="value">{output}</span></div>
</div>
```

`input` / `output` 両方 `null` の場合: `<p class="usage-empty">{dict.empty_problem}</p>`

#### environment ブロックのレンダリング

**`{{ENVIRONMENT_BLOCK}}`** — 各 `summary-item` を順に並べる。label は dict キー:

| label | value（null は `—`） |
|---|---|
| `dict.label_hostname` | `{hostname}` |
| `dict.label_os` | `{os}` |
| `dict.label_cpu` | `{cpu}` |
| `dict.label_ram` | `{ram_total_gb} GB` |
| `dict.label_gpu + " " + index` | `{name} ({memory_total_mb / 1024:.1f} GB)` — gpus[] 各要素を 1 item ずつ |
| `dict.label_cuda_driver` | `CUDA {cuda_version} / driver {gpus[0].driver_version}` — gpus が空配列なら省略 |
| `dict.label_python` | `{python_version}` |

```html
<div class="summary-grid">
  <div class="summary-item"><label>{label}</label><span class="value">{value}</span></div>
  ...
</div>
```

`environment` 自体が `null` / 空 dict の場合: `<p class="usage-empty">{dict.empty_environment}</p>`

#### usage ブロックのレンダリング

**`{{QUICKSTART_BLOCK}}`** — 非 null 時:
```html
<p>{description}</p>
<pre><code>{command}</code></pre>
<p class="usage-note">{verified ? '<span class="usage-verified">' + dict.verified_badge + '</span>' : note}</p>
```
null 時: `<p class="usage-empty">{dict.empty_quickstart}</p>`

**`{{ADVANCED_BLOCK}}`** — 各要素を順に:
```html
<h4>{title}</h4>
<pre><code>{command}</code></pre>
<p class="usage-note">{dict.source_label} {source}{note ? ' — ' + note : ''}</p>
```
空配列時: `<p class="usage-empty">{dict.empty_advanced}</p>`

**`{{DEVELOPER_BLOCK}}`** — 非 null 時:
```html
<p>{description}</p>
<pre><code>{sample_code}</code></pre>
<p class="usage-note">Import: <code>{import_path}</code>{note ? ' — ' + note : ''}</p>
```
null 時: `<p class="usage-empty">{dict.empty_developer}</p>`

#### samples ブロックのレンダリング

**`{{SAMPLES_BLOCK}}`** — 各 item を type 別に:

**`image_pair`**:
```html
<div class="sample-item">
  <h4>{label}</h4>
  <div class="sample-grid sample-grid-2">
    <figure><img src="{input_paths[0]}" alt="input" loading="lazy"><figcaption>{dict.fig_input}</figcaption></figure>
    <figure><img src="{output_paths[0]}" alt="output" loading="lazy"><figcaption>{dict.fig_output}</figcaption></figure>
  </div>
</div>
```

**`image_triple`**:
```html
<div class="sample-item">
  <h4>{label}</h4>
  <div class="sample-grid sample-grid-3">
    <figure><img src="{input_paths[0]}" alt="left" loading="lazy"><figcaption>{dict.fig_left}</figcaption></figure>
    <figure><img src="{input_paths[1]}" alt="right" loading="lazy"><figcaption>{dict.fig_right}</figcaption></figure>
    <figure><img src="{output_paths[0]}" alt="disparity" loading="lazy"><figcaption>{dict.fig_disparity}</figcaption></figure>
  </div>
</div>
```

3D type (`gaussian_splat` / `point_cloud` / `mesh`) では **`data-coord-convention="{metadata.coord_convention or 'unknown'}"`** 属性を必ず付ける。viewer 側がこの値を見て X 軸 180° 回転を適用する。値は `opencv` / `opengl` / `z_up` / `unknown` のいずれか。

**`gaussian_splat`**:
```html
<div class="sample-item">
  <h4>{label}</h4>
  <div class="viewer-3d viewer-gsplat" data-src="{output_paths[0]}" data-coord-convention="{metadata.coord_convention}"></div>
  <p class="usage-note">{dict.note_gaussians} {metadata.gaussian_count}</p>
</div>
```
ビューワ本体は template 末尾の `<script type="module">` が Three.js + `@mkkellogg/gaussian-splats-3d` を CDN importmap 経由で動的初期化。GS viewer は既に `cameraUp=[0,-1,0]` で OpenCV 規約に対応済みのため、現状は `data-coord-convention` を読まない（将来的に opengl 入力を扱う際の予約属性）。

**`point_cloud`**:
```html
<div class="sample-item">
  <h4>{label}</h4>
  <div class="viewer-3d viewer-pointcloud" data-src="{output_paths[0]}" data-coord-convention="{metadata.coord_convention}"></div>
  <p class="usage-note">{dict.note_points} {metadata.point_count}</p>
</div>
```
ビューワは Three.js `PLYLoader` + `THREE.Points`。`data-coord-convention="opencv"` で X 軸 180° 回転 (`points.rotateX(π)`)、`"z_up"` で X 軸 -90° 回転。

**`mesh`**:
```html
<div class="sample-item">
  <h4>{label}</h4>
  <div class="viewer-3d viewer-mesh" data-src="{output_paths[0]}" data-coord-convention="{metadata.coord_convention}"></div>
  <p class="usage-note">{dict.note_format} {metadata.format}</p>
</div>
```
ビューワは Three.js `GLTFLoader` / `OBJLoader`。対応: `.glb` / `.gltf` / `.obj`。`data-coord-convention="opencv"` で X 軸 180° 回転を適用。

**`video`**:
```html
<div class="sample-item">
  <h4>{label}</h4>
  <video class="sample-video" src="{output_paths[0]}" autoplay muted loop playsinline preload="metadata">
    Your browser does not support HTML5 video.
  </video>
</div>
```

空配列時: `<p class="usage-empty">{dict.empty_samples}{note ? ' (' + note + ')' : ''}.</p>`

#### next_actions ブロックのレンダリング

**`{{NEXT_ACTIONS_BLOCK}}`** — 各要素を順に:

```html
<div class="next-action-item">
  <div class="next-action-header">
    <span class="priority-badge priority-{priority}">{priority}</span>
    <strong>{action}</strong>
  </div>
  <p class="usage-note">{reason}</p>
  <!-- command が非 null の場合のみ -->
  <pre><code>{command}</code></pre>
</div>
```

空配列時: `<p class="usage-empty">{dict.empty_next_actions}</p>`

#### HTML エスケープ（共通）

全ブロックでテキスト挿入時は `<`, `>`, `&`, `"`, `'` をエスケープ。属性値は `"` → `&quot;`。

### Step 4: 成果物確認

Phase 0 の「成果物レイアウト」通りに全ファイルが揃っているか確認。

### Step 5: 最終コミットとアーカイブ

**5.1 レポート類を 1 コミット:**
```bash
git status --porcelain
git add reports/ pixi.toml pixi.lock
git commit -m "chore: finalize reproduction reports"
```
`reports/attempts.tsv` と `reports/_baseline_sha` は Phase 0 で `.gitignore` 追加済みなので `git add reports/` には載らない。`reports/` 配下に新規ファイルが無ければ空コミットを skip する。

**5.2 アーカイブ作成**（`status == "success"` のみ、他は skip → `archive_path=null`）:
```bash
REPO_NAME=$(basename "$PWD")
SHORT_SHA=$(git rev-parse --short HEAD)
ARCHIVE_PATH="$(cd .. && pwd)/${REPO_NAME}-${SHORT_SHA}.tar.gz"
git archive --format=tar.gz --prefix="${REPO_NAME}-${SHORT_SHA}/" HEAD -o "${ARCHIVE_PATH}"
```
`git archive HEAD` は追跡ファイルのみ（attempts.tsv / .pixi / モデル重みは含まない）。親ディレクトリに書けない場合は `/tmp/${REPO_NAME}-${SHORT_SHA}.tar.gz` にフォールバック。

**5.3 `report.json.archive_path` 更新**（新規コミット、amend 禁止）:
```bash
git add reports/report.json && git commit -m "chore: record archive path"
```
アーカイブ内部の `report.json.archive_path` は `null` のままだがワーキングツリー側は最新なので Step 6 の出力に実害なし。

**5.4 skip 時:** Step 6 で「⚠️ アーカイブは status=success 時のみ作成されます。現在は `{status}`」を明示。

### Step 6: Next Actions のターミナル出力

`report.json` の `next_actions` / `archive_path` / `status` を読み、そのまま出力する（再生成・再計算しない）。見出し・固定文言は `$REPORT_LANG` に従う。`action` / `reason` は既に Step 1.7 で `$REPORT_LANG` で書かれている前提で再翻訳しない。

LANG=ja（デフォルト）:

```
## 再現完了

ステータス: {status}
アーカイブ: {archive_path or "(status != success のため未作成)"}

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
Archive: {archive_path or "(not created; status != success)"}

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
