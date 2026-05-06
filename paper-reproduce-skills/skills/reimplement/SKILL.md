---
name: reimplement
description: User-invoked orchestration to fully reproduce a CV paper GitHub repository (clone → dep analysis → Pixi env build → inference/training → report). Triggers ONLY when the user types `/reimplement` or `/paper-reproduce:reimplement`. Do NOT auto-invoke based on description match — this skill executes side-effectful operations (git clone, Pixi env build, multi-hour training, archive creation). CWD must be a clone of the target repository. Phase 1 / Phase 4 are gated by JSON Schema validation (schemas/analysis.schema.json, schemas/report.schema.json) to prevent 4 known judgment errors (samples mesh+.ply / paper_claims empty without reason / reproduction_mode mis-classification / feasibility.blockers schema drift).
disable-model-invocation: true
allowed-tools: Bash Read Write Edit Glob Grep Agent
---

# reimplement: 論文リポジトリ全自動再現の orchestration

Phase 0 → Phase 4 を順に実行する。**詳細ロジックは下位スキル / scripts / templates に委譲**し、本ファイルでは各 Phase の **終了契約 (exit contract)** と **Phase 間の routing** だけを定義する。

**NEVER STOP**: 人間に確認しない。`experiment-loop` の Tier 分類に従い自律リトライ。手動停止のみで終了。

**REPORT_LANG**: 環境変数 `$REPORT_LANG` (`ja` デフォルト / `en`) で `report.html` / `report.json` 内のユーザー向け散文の言語を切り替える。値は `bootstrap.sh --lang` で渡される。論文・コード由来の固有名詞は翻訳しない。

## Phase 契約一覧 (compact reference)

| Phase | 主役 SKILL | 出力 | Exit Gate |
|---|---|---|---|
| 0 Init | (orchestration) | `reports/`, `attempts.tsv`, `_baseline_sha` | Pre-flight 5 項目通過 |
| 1 解析 | `repo-analyzer` | `reports/analysis.json` | `check-jsonschema` で `schemas/analysis.schema.json` に validate |
| 2 環境 | `pixi-env-builder` / `dep-converter` / `cuda-dependency-resolver` | `pixi.toml` / `pixi.lock` | `pixi install` 成功 + `torch.cuda.is_available()==True` |
| 3 推論 | `experiment-loop` (Tier) | `reports/telemetry.json`, 推論出力 | デモ/推論コマンド成功 |
| 3.5 学習 (条件付) | `experiment-loop` | `reports/training_metrics.json`, eval 出力 | `paper-claim-audit` 完了 |
| 4 報告 | `usage-documenter` / `sample-embedder` / `templates/RENDERING.md` | `reports/report.{json,html}`, アーカイブ | `check-jsonschema` で `schemas/report.schema.json` に validate |

---

## Phase 0: Initialize

### 成果物レイアウト

```
{repo_root}/
├── pixi.toml            # commit 対象
├── pixi.lock            # commit 対象
└── reports/
    ├── analysis.json       # Phase 1
    ├── attempts.tsv        # 全試行ログ (.gitignore 対象)
    ├── environment.json    # Phase 4 Step 1.4 (scripts/snapshot_env.py)
    ├── training_metrics.json  # Phase 3.5 (scripts/training_watcher.py)
    ├── eval/               # Phase 3.5 eval 出力
    ├── samples/{input,output}/  # Phase 4 Step 1.6
    ├── report.json         # Phase 4 機械可読
    └── report.html         # Phase 4 目視確認

# リポジトリ外 (status=success|partial|failed のみ)
../{repo_name}-{short_sha}.tar.gz
```

### 初期化手順

```bash
git status                                      # CWD が git リポか確認
git stash                                       # 未コミット退避 (あれば)
git remote -v                                   # repo URL 検出
git submodule status                            # submodule 確認
mkdir -p reports
echo -e "attempt\tcommit\tphase\taction\tintent\tresult\terror_tier\terror_summary\tduration_s" > reports/attempts.tsv
echo -e "reports/attempts.tsv\nreports/_baseline_sha" >> .gitignore
git rev-parse HEAD > reports/_baseline_sha      # 既存リポの古い commit を duration 計算で誤って起点にしないため
ls                                              # 依存ファイル一覧 (Phase 1 事前情報)
```

### Pre-flight ガード (Phase 1 進入前に必ず通過、Tier 0 で修正)

```bash
# 1. git identity
git config user.email >/dev/null 2>&1 || git config user.email "claude@anthropic.com"
git config user.name  >/dev/null 2>&1 || git config user.name  "Claude"

# 2. キャッシュ書き込み権限 (.cache 不可なら HF_HOME / TORCH_HOME / MPLCONFIGDIR を /tmp に逃がす)
for d in "$HOME/.cache" /tmp; do [ -w "$d" ] || echo "WARN: $d not writable"; done

# 3. ネットワーク到達
curl -sfm 5 -I https://pypi.org/simple/ >/dev/null || echo "WARN: pypi unreachable"
curl -sfm 5 -I https://huggingface.co       >/dev/null || echo "WARN: hf unreachable"

# 4. host libc (open3d 0.19+ は 2.31 以上必須、cuda-dependency-resolver の条件付き Known issue)
ldd --version | head -1

# 5. CUDA↔PyTorch 互換 (analysis.json 出力後に cross-check、cuda-dependency-resolver)
```

---

## Phase 1: リポジトリ解析

**詳細**: `skills/repo-analyzer/SKILL.md` 参照。出力: `reports/analysis.json` (schema は `schemas/analysis.schema.json`)。

### Feasibility Gate (routing)

`analysis.json.feasibility.status` で分岐:
- `infeasible` → Phase 2 を skip し Phase 4 へ直行 (`status=failed`、`errors=feasibility.blockers`)
- `degraded` → 警告記録の上 Phase 2 へ。`blockers[i].id=gpu_arch_incompatible` なら attempt 1 から `recommended_torch/cuda` で構成
- `ok` → 通常進行

### Phase 1 Exit Gate (schema validation, P0-D)

```bash
check-jsonschema --schemafile /paper-reproduce-skills/schemas/analysis.schema.json reports/analysis.json
```

失敗時は `experiment-loop` の `Tier 2-config` (= analysis.json shape を修正して再生成) として処理し、Phase 2 に進ませない。

このゲートで防ぐもの:
- `feasibility.blockers` の string ↔ object ドリフト
- `paper_claims=[]` のとき `claims_extraction.status` 欠落
- `reproduction_mode=train_optional|train_required` のとき `training_recovery=null`
- `data_acquisition_table[].category` enum 違反

---

## Phase 2: Pixi 環境構築

**詳細**: `skills/pixi-env-builder/SKILL.md` (Type 別フロー) / `skills/dep-converter/SKILL.md` (依存変換) / `skills/cuda-dependency-resolver/SKILL.md` (CUDA 依存解決) / `skills/experiment-loop/SKILL.md` (Tier 分類 + リトライ)。

`analysis.json.dep_type` (A1-F) に基づく変換戦略で `pixi.toml` を生成し、`pixi install` が通り `torch.cuda.is_available()==True` になるまで experiment-loop で自律リトライ。

---

## Phase 3: 推論実行

**詳細**: `skills/experiment-loop/SKILL.md` 参照。

### Step 1: モデル・データダウンロード (統合)

`analysis.json.model_download` (重み) と `analysis.json.data_acquisition_table[]` (dataset) を一緒に取得する。

| dataset の category | 挙動 (= 「諦めない」原則) |
|---|---|
| `bundled` | スキップ |
| `auto-fetch` | probe 済 reachable のため無条件取得 (curl / gdown / huggingface_hub) |
| `assisted` | **必ず取得を試行する**: 既知の direct DL URL があれば curl / gdown を attempt loop で実行 (3 回まで Tier 1 retry)。試行成功で `auto-fetch` 相当として継続。試行で失敗したケースのみ `next_actions` に手動手順を追記。**「assisted だから試さない」は MUST NOT** |
| `gated` | 認証 URL の dry-run probe を attempt 内で実行。401/403 が出た時点で `next_actions` に手動認証手順を追記、Phase 3 / 3.5 自体は継続 |
| `blocked` | gdown 等を 1 回試して "rate-limited" / "domain administrator" 等が確定したら `errors[]` に追加 (P2-B、`experiment-loop` 参照)。`required_for_claims` 非空でも **試行ゼロで blocked 扱いするのは禁止** |

**MUST NOT** (v0.1.1 regression 教訓):
- `data_acquisition_table[].category` の draft 値だけを見て Phase 3.5 起動可否を判定する
- `assisted` / `gated` を「諦めて next_actions 行きにする」だけで終わらせる (= 試行ゼロ regression を再発させる)
- Phase 3 の dataset DL 段で取得が完了していないことを理由に Phase 3.5 を skip する (Phase 3.5 内の attempt loop でも試行する設計)

ディスク容量チェック (DL 開始前):

```bash
AVAIL_GB=$(df --output=avail . | tail -1 | awk '{print $1/1024/1024}')
TOTAL_NEEDED=$(jq -r '[.data_acquisition_table[] | select(.category=="auto-fetch") | .disk_after_extract_gb] | add // 0' reports/analysis.json)
[ "$(echo "$TOTAL_NEEDED > $AVAIL_GB * 0.7" | bc -l)" = "1" ] && echo "WARN: dataset total ${TOTAL_NEEDED} GB > 70% of available ${AVAIL_GB} GB"
```

### Step 2: Headless GUI 対策

Docker image に `/etc/headless_patches/headless_patch.py` (cv2 / open3d / matplotlib モンキーパッチ) が事前配置済み。詳細は `skills/experiment-loop/SKILL.md` の「Headless 環境対策」参照。

### Step 2.5: Telemetry 計測

推論時に `reports/telemetry.json` を出力 (Phase 4 が読む)。計測項目: `peak_vram_mb`, `model_load_time_s`, `inference_fps`, `device`, `fallback_to_cpu`, `precision`。

```python
import time, torch, json
if torch.cuda.is_available():
    torch.cuda.reset_peak_memory_stats()
load_t0 = time.time(); model = ...; load_t1 = time.time()
inf_t0 = time.time(); output = model(input); inf_t1 = time.time()
# Telemetry honesty: model が乗っているデバイスを参照する。is_available() だと CPU fallback 後に True のままで silent false-success になる。
on_gpu = next(model.parameters()).device.type == "cuda"
json.dump({
    "peak_vram_mb": int(torch.cuda.max_memory_allocated() / 1e6) if on_gpu else None,
    "model_load_time_s": round(load_t1 - load_t0, 2),
    "inference_fps": round(1.0 / (inf_t1 - inf_t0), 2) if (inf_t1 > inf_t0) else None,
    "device": torch.cuda.get_device_name(0) if on_gpu else "cpu",
    "fallback_to_cpu": not on_gpu,
    "precision": str(next(model.parameters()).dtype) if hasattr(model, "parameters") else None,
}, open("reports/telemetry.json", "w"), indent=2)
```

### Step 3: デモ/推論スクリプト実行

`experiment-loop` の `inference` 判定フロー (4-Tier) で自律リトライ。成功 → Phase 4 へ (`reproduction_mode=inference_only` の場合) または Phase 3.5 へ (`train_required` / `train_optional` の場合)。

---

## Phase 3.5: Full Training (条件付き)

**起動判定 (MUST 強制起動、v0.1.1 regression 教訓)**: 以下の 2 条件 AND を満たすときは **dataset 取得状況に関わらず必ず Phase 3.5 を起動する**:

- `analysis.json.reproduction_mode ∈ {"train_required", "train_optional"}` (= 全 claim eval に学習が必要 / 一部 claim に学習が必要、のどちらでも起動。`train_optional` でも未カバー claim があるため training は走らせる)
- `analysis.json.paper_claims[]` が非空

両条件 AND を満たさない (= `inference_only` / `paper_claims=[]`) なら smoke が最終結果として Phase 4 へ。

**MUST NOT** (Phase 3.5 を skip してよい唯一のケース以外で skip する判断):
- 「dataset が `assisted` / `gated` / `blocked` で取れない」を理由に skip する → **必ず起動して experiment-loop 内で attempt 試行**
- 「Phase 3 の smoke が success だから十分」と判定する → smoke は健全性確認のみ、claim 再現には full training が必須
- 「データ取得が困難だから failure_recoverability=blocked → Phase 3.5 skip」と短絡する → blocked 判定は Phase 3.5 内の試行が全失敗してから

**所要時間 / GPU 余力 / disk で skip しない**: 「時間制限なし・全自動・claim 達成まで」がコンセプト。Budget 上限なし。

**dataset 取得は Phase 3.5 内の attempt loop で繰り返し試行**: Phase 3 Step 1 で取れなかった `assisted` / `gated` の dataset は、Phase 3.5 の最初に再度 gdown / curl / hf_api を試行する。Phase 3.5 内で取れたら training に進む。3 回試行しても全失敗の場合のみ、claim 単位で `claims_verification[].status=not_evaluated` を記録 (= eval は走らせない、ただし Phase 3.5 の起動自体は記録)。

**詳細実装**: `skills/experiment-loop/SKILL.md` の「Long-running training の fail-fast (P3-C)」節 (watcher 起動 / 検知ルール / Resume) と「データ取得失敗の分類 (P2-B)」節を参照。

### eval 実行 + paper-claim-audit (P0-C)

full training 完了後:

```bash
mkdir -p reports/eval
pixi run python {eval_command} 2>&1 | tee reports/eval/run.log
```

eval 出力を `paper-claim-audit` skill に渡し `reports/_claims.json` を生成、`report.json.claims_verification[]` に転記:

```bash
jq -s '.[0] + {claims_verification: (.[1].results // [])}' \
   reports/report.json reports/_claims.json > reports/report.json.tmp
mv reports/report.json.tmp reports/report.json
rm reports/_claims.json
```

`claims_verification[]` の status enum (`matched` / `within_tolerance` / `missed` / `not_evaluated`) は `schemas/report.schema.json` で enforce。

### ScheduleWakeup の使い方 (P3-B との組み合わせ)

数時間の training は `ScheduleWakeup` で待つ。prompt に **「もし既に完了していたら status だけ報告して終了 — do NOT re-run」** を必ず含める (race ahead 防止)。詳細は下記「核心原則 § Wakeup idempotency」。

---

## Phase 4: レポート生成

### Step 1: 中間ファイル削除

`cleaned.yml` (Type A2/A3)、`build.log` / `inference.log` (attempts.tsv に集約済み)、`_headless_patch.py`、`reports/_gh_*.json`、`reports/_claims.json`、`reports/_render_video.py` 等を削除。

### Step 1.4: 実行環境スナップショット

```bash
pixi run python /paper-reproduce-skills/scripts/snapshot_env.py reports/environment.json
```

### Step 1.5: 使い方情報の抽出

`skills/usage-documenter/SKILL.md` 参照。3 段階 (Quickstart / Advanced / Developer) で `usage` オブジェクトを生成。

### Step 1.6: 入出力サンプルの抽出

`skills/sample-embedder/SKILL.md` 参照。Phase 3 / Phase 3.5 の成功コマンドから入出力ファイルを特定し `reports/samples/` に正規化コピー。

**samples の exit contract** (= P0-D の Phase 4 Step 2 schema gate で enforce):
- `type=mesh` の output は `.glb` / `.gltf` / `.obj` のみ (`.ply` mesh は **必ず glb 化** または `point_cloud` 降格、sample-embedder Step 2.5)
- `type=gaussian_splat` / `point_cloud` の output は `.ply` / `.splat` / `.ksplat`
- `type=video` で 3DGS 由来 (`metadata.rendered_from` 設定済) なら `metadata.ply_compatibility` 必須 (sample-embedder Step 4.5.5)

`samples.category == "mv_to_gaussians"` の場合、必ず動画を主出力にする (sample-embedder Step 4.5.5、`scripts/render_gaussian_video.py`)。

### Step 1.7: Next Actions の生成

`next_actions[]` を生成し Step 2 で `report.json` に組み込む。Step 3 で HTML レンダリング、Step 6 でターミナル出力 (3 箇所同一ソース)。

スキーマ:
```json
{"priority": "high|medium|low", "effort": "low|medium|high", "cost": "free|gpu_upgrade|paid_api|external_data", "action": "string", "reason": "string", "command": "string|null"}
```

**status 別の生成規則**:
- `success`: 検証済み quickstart / advanced 未検証項目 / 別入力で再生成 / ベンチマーク (典型 2-4 件)
- `partial`: 未達 Phase 特定と指示 / `errors` 解消手順 / 軽量パラメータ (典型 3-5 件)
- `failed`: Tier 別根本原因 / 代替アプローチ / 各 `errors[]` 修正候補 / `gpu_arch_incompatible` あれば高優先度 (典型 3-6 件)

**原則**:
- 各項目は独立実行可能。前後依存が強ければ 1 項目にまとめる
- `action` は具体的に書く (×「環境を修正する」/ ○「`pixi add --pypi xformers==0.0.23`」)
- `priority` と `cost` を混同しない: "24GB GPU で full-res" は `cost=gpu_upgrade` なので現手元では `high` に置かない
- `high` は 0-2 件
- `action` / `reason` は `$REPORT_LANG` に従う、`command` は原文ママ

### Step 1.7.5: 失敗の主因サマリ

`status=success` 時はスキップ (`failure_headline=null`、`failure_recoverability=null`)。`failed` / `partial` / Phase 1 `infeasible` のみ生成。

`failure_headline`: `errors[]` の中で**最も上流のブロッカー** (これを直さないと他のエラーが解決しても先に進まない) を 1 つ選び、**1-2 文 (最大 120 字、改行禁止)** で圧縮。固有名詞・パッケージ名・ファイル名は原文ママ。`$REPORT_LANG` に従う。

`failure_recoverability` 3 値 enum (上から順、最初にマッチ):

| 値 | 判定基準 | バッジ色 |
|---|---|---|
| `blocked` | 非公開リソース / 認証必須 / 著者対応待ち。`errors[]` に `missing_private_*`, `needs_auth`, `private_repo`, `license_restricted` 等 | 赤 |
| `hardware` | GPU/CPU/RAM/disk 不足 (= 強い PC で動く)。`errors[]` に `OOM`, `no kernel image`, `gpu_arch_incompatible` (Step 4 まで失敗), `disk_full`, `vram_insufficient` | 橙 |
| `fixable` | 設定/コード/依存修正で動く。`broken_setup_script`, `syntax_error`, `version_mismatch` 等。Tier 0 / 1 / 2-config 主因 | 黄 |

**MUST**: `errors[]` が空でも `status != success` なら何かしら判定 (Phase 2 SegFault 等の未分類は `fixable`)。判定は `errors[]` と `attempts.tsv` から Claude が推論 (機械的ヒューリスティクスではなく文脈判断)。

### Step 1.8: 関連 GitHub Issue / PR の集約検索

`status` が `failed` / `partial` / `infeasible` のときのみ。`analysis.json.github_slug` を使って同リポジトリの Issue / PR を `gh` で集約。`success` 時はスキップ。

```bash
GITHUB_SLUG=$(jq -r '.github_slug // empty' reports/analysis.json)
[ -n "$GITHUB_SLUG" ] && bash /paper-reproduce-skills/scripts/search_github_issues.sh \
    --repo "$GITHUB_SLUG" --kind both --limit 3 \
    --query "<error_summary 先頭 6 単語>" \
    --query "<次の error_summary>" \
    --output reports/_gh_aggregate.json && \
python3 /paper-reproduce-skills/scripts/build_related_issues_block.py \
    --input reports/_gh_aggregate.json \
    --i18n /paper-reproduce-skills/templates/i18n.json \
    --lang "${REPORT_LANG:-ja}" --max 10 \
    --output reports/_related_issues_block.html
```

`reports/_gh_aggregate.json.results[]` の上位 10 件を `report.json.related_issues[]` に転記。`gh` 未認証 / rate-limit / 0 件はすべて空配列で graceful。

### Step 2: reports/report.json 生成 (機械可読、SSOT)

スキーマは `schemas/report.schema.json` 参照 (canonical)。主要フィールド: `repo_name`, `repo_url`, `overview`, `problem`, `status`, `failure_headline`, `failure_recoverability`, `dep_type`, `total_attempts`, `duration_total_s`, `pixi_toml_hash`, `errors`, `environment`, `telemetry`, `usage`, `samples`, `next_actions`, `related_issues`, `claims_verification`, `archive_path`, `plugin_version`。

**埋め込み規則** (各フィールドの転記元):
- `overview` / `problem` → `analysis.json.{overview,problem}`
- `environment` → `reports/environment.json` (Step 1.4)
- `usage` → Step 1.5 (取れなかった階層は `null`、`advanced` のみ空配列 `[]`)
- `samples` → Step 1.6
- `next_actions` → Step 1.7
- `failure_headline` / `failure_recoverability` → Step 1.7.5 (`success` 時 null)
- `related_issues` → Step 1.8 の `_gh_aggregate.json.results[]` 上位 10 件
- `claims_verification` → Phase 3.5.7 の `_claims.json.results[]` (Phase 3.5 起動なしなら `[]`)
- `archive_path` → Step 5.2 で更新 (Step 2 時点は `null` 仮置き)

**status 判定** (上から順、最初にマッチ):
- `failed`: Phase 1 `infeasible` / `pixi install` 最終失敗 / 推論ゼロ件
- `partial`: pixi 成功 + 推論 1 件以上 + 未達あり
- `success`: pixi 成功 + quickstart 全成功

**Phase 3.5 完走時の追加ルール**: `claims_verification[]` 非空のとき、上記判定の **後段で** 上書き:
- 全 claim `matched` / `within_tolerance` → `success`
- `missed` 1 件以上 / eval crash / 全 `not_evaluated` → `partial`

**MUST NOT**: Tier 3 到達時の `partial` へのデフォルト落とし。

**TSV 値検証** (Step 2 開始時に必須): `attempts.tsv` の各列が `experiment-loop` の正規形に従っているか確認、違反あれば `report.json` 生成前に sed 置換 (`fail`→`failed` 等)。

```bash
awk -F'\t' 'NR>1 && $3 !~ /^phase[0-4]$/ {print "INVALID phase row "NR": "$3}' reports/attempts.tsv
awk -F'\t' 'NR>1 && $6 !~ /^(success|failed|crashed|timed_out)$/ {print "INVALID result row "NR": "$6}' reports/attempts.tsv
awk -F'\t' 'NR>1 && $7 !~ /^(tier[013]|tier2-(config|hardware)|-)$/ {print "INVALID tier row "NR": "$7}' reports/attempts.tsv
```

**duration_total_s** (過小見積もり防止のクロスチェック):

```bash
SUM=$(awk -F'\t' 'NR>1 {s+=$9} END {print s+0}' reports/attempts.tsv)
BASELINE_SHA=$(cat reports/_baseline_sha 2>/dev/null || echo "")
if [ -n "$BASELINE_SHA" ] && git merge-base --is-ancestor "$BASELINE_SHA" HEAD 2>/dev/null; then
    FIRST=$(git log --format='%at' --reverse "${BASELINE_SHA}..HEAD" | head -1)
    LAST=$(git log --format='%at' | head -1)
    SPAN=$((LAST - ${FIRST:-$LAST}))
else
    SPAN=0
fi
DURATION_TOTAL=$(( SUM > SPAN ? SUM : SPAN ))   # SUM < SPAN*0.7 なら計測漏れ、ただし大きい方を採用
```

#### Phase 4 Step 2 Exit Gate (schema validation, P0-D)

```bash
check-jsonschema --schemafile /paper-reproduce-skills/schemas/report.schema.json reports/report.json
```

失敗時は同 Step 内で修正、ゲート通過まで Step 3 (HTML 生成) に進ませない。このゲートで防ぐもの: `samples.items[].type=mesh + .ply` (= P1-A 違反)、`type=gaussian_splat | point_cloud` の拡張子違反、3DGS video の `ply_compatibility` 欠落、`claims_verification[].status` enum 違反、`image_pair`/`image_triple` の paths 件数不一致。

### Step 3: reports/report.html 生成 (目視確認)

```bash
cp /paper-reproduce-skills/templates/report.html reports/report.html
cp /paper-reproduce-skills/templates/view.sh     reports/view.sh
chmod +x reports/view.sh
```

詳細レンダリング規則 (i18n placeholders / OVERVIEW/PROBLEM/ENVIRONMENT/USAGE/SAMPLES/NEXT_ACTIONS/CLAIMS_VERIFICATION ブロックの HTML 雛形 / HTML エスケープ規則): **`templates/RENDERING.md` 参照**。

`{{T_*}}` 系・`{{I18N_JSON_INLINE}}` は `templates/i18n.json[$LANG_CODE]` から置換、`{{*_BLOCK}}` は動的ブロックを RENDERING.md に従いレンダリング。

**MUST NOT**: `<style>` 内変更 / プレースホルダー名追加・削除 / 新セクション追加 / `<html lang>` を i18n 以外で書き換え。

### Step 3.5: report.html の最終ゲート (finalize_report.py)

Step 3 で取りこぼした `{{...}}` を非表示化する保険。`status` / 値の有無に応じた flag を渡す:

```bash
LANG_CODE="${REPORT_LANG:-ja}"; case "$LANG_CODE" in ja|en) ;; *) LANG_CODE=ja ;; esac
FLAG_ARGS=()
STATUS=$(jq -r '.status' reports/report.json)
HEADLINE=$(jq -r '.failure_headline // empty' reports/report.json)
ARCHIVE=$(jq -r '.archive_path // empty' reports/report.json)
CLAIMS_COUNT=$(jq -r '.claims_verification | length' reports/report.json)
case "$STATUS" in failed|partial) FLAG_ARGS+=(--flag ERRORS) ;; esac
[ -n "$HEADLINE" ]      && FLAG_ARGS+=(--flag FAILURE_HEADLINE)
[ -n "$ARCHIVE" ]       && FLAG_ARGS+=(--flag ARCHIVE_PATH)
[ "$CLAIMS_COUNT" -gt 0 ] && FLAG_ARGS+=(--flag CLAIMS_VERIFICATION)
case "$STATUS" in failed|partial|infeasible) FLAG_ARGS+=(--flag RELATED_ISSUES) ;; esac

python3 /paper-reproduce-skills/scripts/finalize_report.py \
    --input reports/report.html --i18n /paper-reproduce-skills/templates/i18n.json \
    --lang "$LANG_CODE" "${FLAG_ARGS[@]}"
```

**ASSERTION**: 完了後 `grep -c '{{[A-Z]' reports/report.html` が **0** であること。**`<tr>` 行数 == `attempts.tsv` データ行数**。

### Step 4: 成果物確認

「成果物レイアウト」通りに全ファイルが揃っているか確認。

### Step 5: 最終コミットとアーカイブ

**5.1 レポート類を 1 コミット + tracked 確認**:

```bash
git status --porcelain
git add reports/ pixi.toml pixi.lock
git commit -m "chore: finalize reproduction reports"

# sample paths が git に乗ったか検証 (.gitignore 衝突 / symlink 切れ早期検出)
while IFS= read -r path; do
    [ -z "$path" ] && continue
    full="reports/$path"
    [ -L "$full" ] && { echo "FAIL: $full is a symlink (cp -L で実体コピーに置換)"; exit 1; }
    git ls-files --error-unmatch -- "$full" >/dev/null 2>&1 || {
        echo "FAIL: $full not tracked (.gitignore に negation rule '!reports/...' 追記し git add -f)"; exit 1;
    }
done < <(jq -r '.samples.items[]? | .input_paths[]?, .output_paths[]?' reports/report.json)
```

**5.2 アーカイブ作成** (`status` ∈ {success, partial, failed} なら生成。Phase 1 `infeasible` で 5.1 未実行のときのみ skip → `archive_path=null`):

```bash
REPO_NAME=$(basename "$PWD"); SHORT_SHA=$(git rev-parse --short HEAD)
ARCHIVE_PATH="$(cd .. && pwd)/${REPO_NAME}-${SHORT_SHA}.tar.gz"
git archive --format=tar.gz --prefix="${REPO_NAME}-${SHORT_SHA}/" HEAD -o "${ARCHIVE_PATH}"
# 親に書けない場合は /tmp/${REPO_NAME}-${SHORT_SHA}.tar.gz に fallback
```

**5.3 `report.json.archive_path` 更新** (新規コミット、amend 禁止):

```bash
git add reports/report.json && git commit -m "chore: record archive path"
```

### Step 6: Next Actions のターミナル出力

`report.json` の `next_actions` / `archive_path` / `status` を読みそのまま出力 (再生成・再計算しない)。

LANG=ja:
```
## 再現完了
ステータス: {status}
アーカイブ: {archive_path or "(infeasible のため未作成)"}

## 次のアクション
1. [HIGH] {action}
   理由: {reason}
   $ {command}     # command が null なら省略
2. [MEDIUM] ...
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
```

`next_actions` 空 → ja:「特筆すべき次のアクションはありません。」 / en: "No notable next actions."

---

## 核心原則

### Git 運用ルール (全 Phase 共通)

- `git commit --amend` 禁止 (archive SHA と attempts.tsv の SHA ズレ回避)
- `git reset --hard HEAD~1` は Experiment Loop 失敗復旧専用 (`experiment-loop` 参照)
- `git push --force` 禁止
- 各 commit ごとに START_TIME / END_TIME を測り `attempts.tsv` に 1 行追記 (成否問わず)
- メッセージ: 命令形・英語・72 文字以内 (例: `attempt #3: bump libc to 2.31 for open3d`)

### NEVER STOP

失敗しても止まらない。`experiment-loop` の Tier 分類で自律修正・再試行。停止条件は全 Phase 完了または手動停止のみ。

### Background / long-running は絶対パス (P3-A)

`&` を伴う background タスクと long-running command は対象を絶対パスで指定。`cd` で CWD を変えると次のコマンドにも引き継がれる:

```
NG: cd data && curl -o Points.zip URL &
OK: curl -o /workspaces/.../data/Points.zip URL &
```

repo 内ツールが相対パス前提なら `(cd repo && tool args)` でサブシェルに閉じ込める。

### ScheduleWakeup の idempotency (P3-B)

```
ScheduleWakeup({
  delaySeconds: 1200,
  reason: "checking 30k iter training progress",
  prompt: "Check whether <task> finished.
           **If already done in a prior turn, just report current state and exit — do NOT re-run.**
           Otherwise: ..."
})
```

Phase 3 長期 DL / Phase 3.5 training を待つ場合は必ずこのパターン。

### Watcher loop は実 PID 監視 (P3-A2)

`pgrep -f "<pattern>"` は eval 後の bash command 文字列に pattern が含まれて自分自身を見つけ self-grep deadlock する。

```bash
# NG (self-grep deadlock):
until ! pgrep -f "mesh_extract" >/dev/null; do sleep 15; done

# OK (filter own pid):
SELF=$$
until ! pgrep -f "mesh_extract" | grep -v "^${SELF}$" | grep -q .; do sleep 15; done

# 一番安全 (実 PID を保存):
PID_TO_WATCH=$(cat /tmp/tetra.pid)
while kill -0 "$PID_TO_WATCH" 2>/dev/null; do sleep 15; done
```

`scripts/training_watcher.py` も `--pid` で実 PID を受け取り `os.kill(pid, 0)` で監視する設計。

### 依存関係の原則

`skills/pixi-env-builder/SKILL.md` / `skills/cuda-dependency-resolver/SKILL.md` / `skills/dep-converter/SKILL.md` に委譲。Divide-and-Conquer / no-build-isolation / チャンネル順 / CUDA 統一はそれらのスキル内で定義。ここでは重複して書かない。
