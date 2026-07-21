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

**REPRODUCE_LEVEL**: 環境変数 `$REPRODUCE_LEVEL` (`inference` デフォルト / `full`、`bootstrap.sh --full` で full) が再現の**範囲**を決める:

| レベル | 範囲 | Phase 3.5 |
|---|---|---|
| `inference` | 推論再現まで (デモ/推論を論文デフォルト引数で完走させる)。claim は**抽出・表示のみ** (`not_evaluated`)。ベンチマーク dataset の取得もしない | 起動しない |
| `full` | 学習 + eval + claim 定量評価まで含むフル検証 | 条件を満たせば必ず起動 |

どちらのレベルでも `report.json.reproduce_level` に値を記録する (schema required)。inference の success は「推論再現の成功」であり claim 検証を含意しない — その区別は `reproduce_level` と `claims_verification[].status=not_evaluated` がレポート上で明示する。

## Phase 契約一覧 (compact reference)

| Phase | 主役 SKILL | 出力 | Exit Gate |
|---|---|---|---|
| 0 Init | (orchestration) | `reports/`, `attempts.tsv`, `_baseline_sha` | Pre-flight 5 項目通過 |
| 1 解析 | `repo-analyzer` | `reports/analysis.json` | `check-jsonschema` で `schemas/analysis.schema.json` に validate |
| 2 環境 | `pixi-env-builder` / `dep-converter` / `cuda-dependency-resolver` | `pixi.toml` / `pixi.lock` | `pixi install` 成功 + `torch.cuda.is_available()==True` |
| 3 推論 | `experiment-loop` (Tier) | `reports/telemetry.json`, 推論出力 | デモ/推論コマンド成功 |
| 3.5 学習+claim 検証 (`REPRODUCE_LEVEL=full` のみ) | `experiment-loop` | `reports/training_metrics.json`, eval 出力, `reports/_claims.json` | `scripts/check_claims.py` 完了 (P0-C) |
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
    ├── telemetry.json      # Phase 3 Step 2.5
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

### Step 1.0: 手動 provisioning 資産の配置 (manual-asset-provisioner)

データ DL より**先に**、`analysis.json.manual_assets[]`（SMPL/SMAL 系などライセンス登録必須で自動 DL 不可の資産）を `/manual-assets`（read-only マウント）から repo 期待パスへ配置する。**詳細**: `skills/manual-asset-provisioner/SKILL.md` 参照。

- `manual_assets` 空 / 無し → skip。
- present（レジストリに在り）→ `repo_expected_path` へコピー + `.gitignore` 追記し続行。**配置物は git / 成功アーカイブに絶対に入れない**（ライセンス上の再配布禁止。Phase 4 の `git archive HEAD` は tracked-only なので `.gitignore` で保証）。
- missing → `next_actions` に取得 URL + 配置先を記録し、`required_for_claims` 非空なら `errors[]` に `manual_asset_missing` を追加。**Phase 3/3.5 は止めない**（NEVER STOP）。**自動 DL / ミラー取得は MUST NOT**。

### Step 1: モデル・データダウンロード (統合)

`analysis.json.model_download` (重み) と `analysis.json.data_acquisition_table[]` (dataset) を一緒に取得する。

**レベルによる取得範囲**:
- `REPRODUCE_LEVEL=inference`: 取得するのは **重み (`model_download`) + デモ/推論に必要な入力データのみ** (多くは `bundled` か小容量)。ベンチマーク dataset (`required_for_claims` 非空の大容量 dataset) は**取得しない** — claim eval を行わないため不要。下の category 別挙動表は full レベル専用。
- `REPRODUCE_LEVEL=full`: 従来どおり全 dataset を category 別挙動表 (=「諦めない」原則) に従い取得する。

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

### Step 3: デモ/推論スクリプト実行 (P0-E 手続き的 enforcement)

Phase 3 Step 3 は **2 sub-step に分かれる**。Step 3a を完了せずに Step 3b に進むのは **Tier 0 違反**。Step 3b で paper-default success が記録されないまま Phase 4 に進むのも **Tier 0 違反**。

#### Step 3a: paper-default args の抽出 (MUST、所要 5-15 分)

attempt loop 開始前に必ず実施し、**物理的成果物として `reports/_paper_default_args.json` を残す**。

1. 以下を順に grep し、**全推論引数のデフォルト値**を抽出:
   - `README.md` の "Quickstart" / "Inference" / "Demo" 節
   - `examples/*.md` / `examples/*.py`
   - `configs/inference*.yaml` / `configs/default*.yaml`
   - `demo*.py` / `inference*.py` の argparse `default=`
2. 抽出結果を `reports/_paper_default_args.json` に保存:
   ```json
   {
     "command_template": "pixi run python -m <module> --input <X> --output <Y>",
     "defaults": {
       "--num-views":            {"value": 32,   "source": "configs/default.yaml:8"},
       "--texture-size":         {"value": 1024, "source": "README.md:47"},
       "--num-inference-steps":  {"value": 50,   "source": "configs/default.yaml:12"}
     },
     "reduced_demo_modes": [
       {"name": "quickstart", "args": {"--num-views": 4, "--texture-size": 256}, "source": "README.md:19", "note": "著者が明示的に reduced demo として宣言"}
     ],
     "notes": "抽出理由 / 例外メモ"
   }
   ```
3. 抽出が困難 (configs / README に明示なし、CLI default のみ) の場合は `defaults={}` で保存し、`notes` に「argparse default に委ねる」旨を記録。空の `_paper_default_args.json` を残すこと自体は許可される (= Step 3a 完了の証跡)
4. **MUST NOT**: `_paper_default_args.json` を作らずに Step 3b に進む / 抽出値を Claude が "smoke 用に縮小" して保存する (= 改ざん)

#### Step 3b: paper-default attempt + experiment-loop

最初の attempt (= **「P0-E reference attempt」**) は `reports/_paper_default_args.json.defaults` の **全値を渡して実行**。`attempts.tsv.intent` に必ず `"P0-E paper-default attempt; args from {source}"` を含める。

成否判定:

| 結果 | 次の動作 |
|---|---|
| **success** | Phase 4 へ (`reproduction_mode=inference_only`) または Phase 3.5 へ (`train_*`) |
| **OOM (Tier 2-hardware)** | OOM ladder。各 ladder step の `intent` に「OOM で {param} を半減 (Step N)」のような **物理理由** を明記。`"to save time"` / `"for quick smoke"` / `"短時間で動作確認"` は禁止 (= Tier 0 違反) |
| **コード修正で直る (Tier 1 / 2-config)** | 修正後、**再度 paper-default の全値で実行**。reduced-param で「とりあえず動かす」は **MUST NOT** |

**reduced-param 試行** (= デフォルトより小さい値、`reduced_demo_modes` 含む) は **paper-default attempt が success になった後** の追加 attempt としてのみ許可。`attempts.tsv` に paper-default success の行 (= `intent` に `P0-E paper-default attempt` を含む success 行) が無いまま Phase 4 に進むのは **Tier 0 違反**。

`experiment-loop` の `inference` 判定フロー (4-Tier) は Step 3b の中で発動する。詳細は `skills/experiment-loop/SKILL.md` 参照。

---

## Phase 3.5: Full Training + Claim 検証 (`REPRODUCE_LEVEL=full` のみ)

**レベルゲート (最初に判定)**:

- `REPRODUCE_LEVEL=inference` (デフォルト) → **Phase 3.5 は起動しない**。ただし `paper_claims[]` 非空なら、レポートの誠実さのために claim を `not_evaluated` として記録する:

  ```bash
  # _observed.json を渡さない = 全 claim が not_evaluated になる (check_claims.py の仕様)
  python3 /paper-reproduce-skills/scripts/check_claims.py \
      --analysis reports/analysis.json --output reports/_claims.json
  ```

  生成した `_claims.json` は Phase 4 Step 2 で通常どおり転記する。「検証していないのに検証済みに見える」ことを防ぐのが目的で、`reproduce_level=inference` + 全行 `not_evaluated` の組で「検証は範囲外だった」ことがレポートから読める。

- `REPRODUCE_LEVEL=full` → 以下の起動判定に進む。

**起動判定 (full のみ。MUST 強制起動、v0.1.1 regression 教訓 + v0.1.7 未検証 success 封鎖)**:

- `analysis.json.paper_claims[]` が **非空なら dataset 取得状況に関わらず必ず Phase 3.5 を起動する**。
  - `reproduction_mode ∈ {"train_required", "train_optional"}` → full training + eval + claim 検証 (`train_optional` でも未カバー claim があるため training は走らせる)
  - `reproduction_mode = "inference_only"` → **eval-only モード**: training は skip し、公開重みで eval + claim 検証だけを実行する。「inference_only だから claim は検証不要」は **MUST NOT** (= quickstart 成功のみで success を名乗る経路の封鎖)
- `paper_claims=[]` (claims_extraction.status で理由記録済み) の場合のみ Phase 3.5 全体を skip し、smoke が最終結果として Phase 4 へ。

**MUST NOT** (Phase 3.5 を skip してよい唯一のケース以外で skip する判断):
- 「dataset が `assisted` / `gated` / `blocked` で取れない」を理由に skip する → **必ず起動して experiment-loop 内で attempt 試行**
- 「Phase 3 の smoke が success だから十分」と判定する → smoke は健全性確認のみ、claim 再現には full training が必須
- 「データ取得が困難だから failure_recoverability=blocked → Phase 3.5 skip」と短絡する → blocked 判定は Phase 3.5 内の試行が全失敗してから

**所要時間 / GPU 余力 / disk で skip しない**: 「時間制限なし・全自動・claim 達成まで」がコンセプト。Budget 上限なし。

**dataset 取得は Phase 3.5 内の attempt loop で繰り返し試行**: Phase 3 Step 1 で取れなかった `assisted` / `gated` の dataset は、Phase 3.5 の最初に再度 gdown / curl / hf_api を試行する。Phase 3.5 内で取れたら training に進む。3 回試行しても全失敗の場合のみ、claim 単位で `claims_verification[].status=not_evaluated` を記録 (= eval は走らせない、ただし Phase 3.5 の起動自体は記録)。

**詳細実装**: `skills/experiment-loop/SKILL.md` の「Long-running training の fail-fast (P3-C)」節 (watcher 起動 / 検知ルール / Resume) と「データ取得失敗の分類 (P2-B)」節を参照。

### eval 実行 + claim 検証 (P0-C)

full training 完了後 (eval-only モードでは公開重み配置後)、3 ステップで検証する。**「結果を出したエージェントが判定も書く」構造を避ける**ため、抽出 (zero-context サブエージェント) と判定 (決定論的スクリプト) を分離している:

**(1) eval 実行**:

```bash
mkdir -p reports/eval
pixi run python {eval_command} 2>&1 | tee reports/eval/run.log
```

**(2) observed 抽出 (zero-context サブエージェント)**: metric 名一覧だけを渡し (**paper_target は渡さない** = 目標値へ数字を寄せるバイアスの遮断)、`Agent` tool で新規サブエージェントに抽出させる:

```bash
jq '{results: [.paper_claims[] | {id, metric_name}]}' reports/analysis.json > reports/_claims_metrics.json
```

サブエージェントへの指示 (会話 context を持たない新規 Agent で実行):
- 入力: `reports/_claims_metrics.json` の metric 一覧と `reports/eval/` 以下のファイルのみ。それ以外の事前情報を与えない
- 各 metric について `reports/_observed.json` に記録: `{"results": [{"id", "observed": <number>, "evidence_path": "reports/eval/...", "evidence_snippet": "<数値を含む行の原文そのまま>"}]}`
- `evidence_path` はテキストファイル (log / json / csv) を指すこと。`evidence_snippet` は**ファイル中に実在する行をそのままコピー**すること (check_claims.py が実在照合する)。単位は snippet 中の表記と揃える
- eval 出力に存在しない metric はエントリを**書かない** (捏造禁止。無ければ not_evaluated になるだけ)

**(3) 決定論的判定 (`scripts/check_claims.py`)**: tolerance のパース、evidence の実在・snippet 照合、`matched / within_tolerance / missed / not_evaluated` の判定はすべてコードが行う (LLM は判定に関与しない):

```bash
python3 /paper-reproduce-skills/scripts/check_claims.py \
    --analysis reports/analysis.json \
    --observed reports/_observed.json \
    --output reports/_claims.json
```

check_claims.py は **必ず exit 0 + `_claims.json` を書く** (observed 欠落・evidence 不正はその claim を `not_evaluated` に降格し `audit.evidence_failures` に理由を記録)。判定規則 (matched = 方向を考慮して target 以上 / within_tolerance = tolerance 帯内 / 方向不明 metric は matched に到達しない) はスクリプト docstring が正典。

**(4) report.json へ転記** (ファイル欠落でも SSOT を壊さない):

```bash
if [ -f reports/_claims.json ]; then
    jq -s '.[0] + {claims_verification: (.[1].results // [])}' \
       reports/report.json reports/_claims.json > reports/report.json.tmp
    mv reports/report.json.tmp reports/report.json
fi
```

`claims_verification[]` の status enum は `schemas/report.schema.json` で enforce。`status ∈ {matched, within_tolerance}` の行は `observed` / `evidence_path` 非 null が schema で必須 (= 根拠なしの「再現成功」はゲートを通らない)。

### ScheduleWakeup の使い方 (P3-B との組み合わせ)

数時間の training は `ScheduleWakeup` で待つ。prompt に **「もし既に完了していたら status だけ報告して終了 — do NOT re-run」** を必ず含める (race ahead 防止)。詳細は下記「核心原則 § Wakeup idempotency」。

---

## Phase 4: レポート生成

### Step 1: 中間ファイル削除

`cleaned.yml` (Type A2/A3)、`build.log` / `inference.log` (attempts.tsv に集約済み)、`_headless_patch.py`、`reports/_gh_*.json`、`reports/_claims.json`、`reports/_observed.json`、`reports/_claims_metrics.json`、`reports/_render_video.py` 等を削除。

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

**MUST NOT (P0-E ポテンシャル最大化との整合)**:
- **`status=success` の next_action に「論文デフォルト引数で再実行」を載せない** (例: 「`--num_inference_steps` を 50 に戻して再実行」「`iterations` を 30000 に戻す」「frame 数をデフォルトに戻す」等)。これが必要に見えた時点で、Phase 3 が論文デフォルトで動かしていなかった証拠 = 核心原則 P0-E 違反。**status を `partial` に再考し**、当該 next_action は `partial` 側で「未達 Phase の指示」として記録する
- `success` で `cost=free` の「論文デフォルトに戻す」項目は禁止 (= 自分で削った物を user に戻させる丸投げ)。`cost=gpu_upgrade` (= ハード制約で削減した正当な縮小の補完) なら可
- 「smoke 確認は最小構成で十分」を理由に、デフォルト品質での再実行を `next_actions` 任せにする運用

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

スキーマは `schemas/report.schema.json` 参照 (canonical)。主要フィールド: `repo_name`, `repo_url`, `overview`, `problem`, `status`, `reproduce_level`, `failure_headline`, `failure_recoverability`, `dep_type`, `total_attempts`, `duration_total_s`, `inference_runtime_s`, `pixi_toml_hash`, `errors`, `environment`, `telemetry`, `usage`, `samples`, `next_actions`, `related_issues`, `claims_verification`, `archive_path`, `plugin_version`。

**埋め込み規則** (各フィールドの転記元):
- `reproduce_level` → env `$REPRODUCE_LEVEL` (`inference` | `full`) をそのまま記録
- `overview` / `problem` → `analysis.json.{overview,problem}`
- `environment` → `reports/environment.json` (Step 1.4)
- `usage` → Step 1.5 (取れなかった階層は `null`、`advanced` のみ空配列 `[]`)
- `samples` → Step 1.6
- `next_actions` → Step 1.7
- `failure_headline` / `failure_recoverability` → Step 1.7.5 (`success` 時 null)
- `related_issues` → Step 1.8 の `_gh_aggregate.json.results[]` 上位 10 件
- `claims_verification` → `_claims.json.results[]` (full: Phase 3.5「eval 実行 + claim 検証 (P0-C)」の判定結果 / inference: レベルゲートで生成した全行 `not_evaluated`)。`paper_claims=[]` の場合のみ `[]`
- `inference_runtime_s` → **`REPRODUCE_LEVEL=inference` のときのみ** 記録する推論そのものの wall-clock (秒)。出典は attempts.tsv の **P0-E reference attempt** (phase3 / result=success / intent に `P0-E paper-default attempt` を含む行) の `duration_s`。デモ/推論の実行時間であり `duration_total_s` (再現全体) とは別物 — env build / dataset DL / 失敗試行を含めない。full レベル、または推論の wall-clock が特定できない場合は `null`。抽出は下の duration_total_s ブロック直後のスニペット参照
- `archive_path` → Step 5.2 で更新 (Step 2 時点は `null` 仮置き)

**status 判定** (上から順、最初にマッチ):
- `failed`: Phase 1 `infeasible` / `pixi install` 最終失敗 / 推論ゼロ件
- `partial`: pixi 成功 + 推論 1 件以上 + 未達あり
- `success`: pixi 成功 + quickstart 全成功

**Phase 3.5 完走時の追加ルール (`REPRODUCE_LEVEL=full` のみ)**: `claims_verification[]` 非空のとき、上記判定の **後段で** 上書き:
- 全 claim `matched` / `within_tolerance` → `success`
- `missed` 1 件以上 / eval crash / 全 `not_evaluated` → `partial`

**MUST NOT** (両方向のガード):
- Tier 3 到達時の `partial` へのデフォルト落とし (悲観方向)
- **未検証 success (楽観方向、P0-C 対称ガード、`REPRODUCE_LEVEL=full` のみ)**: full なのに `paper_claims[]` 非空で `claims_verification[]` が空、または全件 `not_evaluated` のまま `status=success` を出す。この場合 status は `partial` とし、`not_evaluated` の理由 (`_claims.json.audit.evidence_failures`) を `errors[]` / `next_actions[]` に反映する。「claim を検証していないが動いた」は full の success ではない
- `reproduce_level` の偽記録: inference で実行したのに `full` と記録する (またはその逆)

**inference レベルの success**: claim 検証は範囲外なので、全行 `not_evaluated` でも上記の基本判定 (pixi 成功 + quickstart 全成功 → success) のままでよい。範囲の限定は `reproduce_level=inference` としてレポートに明示される。full の検証を促す場合は `next_actions[]` に「`./bootstrap.sh --full <repo>` で claim 定量評価まで実施」(priority=medium, cost=free) を 1 件入れる。

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

**inference_runtime_s** (推論の wall-clock、`REPRODUCE_LEVEL=inference` のみ): P0-E reference attempt の実行時間だけを抜き出す (env build / DL / 失敗試行は含めない)。full レベルでは `null` のまま。

```bash
INFERENCE_RUNTIME_S=null
if [ "${REPRODUCE_LEVEL:-inference}" = "inference" ]; then
    # phase3 の成功行のうち P0-E paper-default reference attempt の duration_s。
    # 複数該当時は最後の成功行 (reduced/CPU fallback で再成功したケースの実測を優先)。
    V=$(awk -F'\t' 'NR>1 && $3=="phase3" && $6=="success" && $5 ~ /P0-E paper-default attempt/ {v=$9} END{if(v!="")print v+0}' reports/attempts.tsv)
    [ -n "$V" ] && INFERENCE_RUNTIME_S="$V"
fi
# INFERENCE_RUNTIME_S を report.json.inference_runtime_s にそのまま (数値 or null) 埋める
```

P0-E 行が success で終わっていない (= OOM ladder / arch upgrade の fallback attempt で初めて推論が通った) 場合は、実際にサンプル出力を生成した phase3 success 行 (model_download 行ではなく demo/inference 実行行) の `duration_s` を採用する。

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
INFER_RT=$(jq -r '.inference_runtime_s // empty' reports/report.json)
case "$STATUS" in failed|partial) FLAG_ARGS+=(--flag ERRORS) ;; esac
[ -n "$HEADLINE" ]      && FLAG_ARGS+=(--flag FAILURE_HEADLINE)
[ -n "$ARCHIVE" ]       && FLAG_ARGS+=(--flag ARCHIVE_PATH)
[ "$CLAIMS_COUNT" -gt 0 ] && FLAG_ARGS+=(--flag CLAIMS_VERIFICATION)
[ -n "$INFER_RT" ]      && FLAG_ARGS+=(--flag INFERENCE_RUNTIME)
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
検証レベル: {reproduce_level}   # inference なら「(claim 定量評価は --full で実施)」を添える
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
Level: {reproduce_level}   # for inference add "(run with --full for quantitative claim eval)"
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

### ポテンシャル最大化 (Maximum Potential, P0-E)

このスキルの最終成果物は **「論文が提案する手法のポテンシャルを実機で示すレポート」** であり、smoke test ("it works") ではない。動作確認は途中目標。「動いた」だけのレポートには価値がない — **手元の HW 制約の中で論文の最大出力を引き出すこと** がレポート最大の目的。

**目標優先順位** (上から):

1. claim 再現 (`REPRODUCE_LEVEL=full` のとき、Phase 3.5 で `paper_claims[]` 達成)
2. **論文・公式コードのデフォルト引数で動かす** — README / `examples/` / `configs/*.yaml` の宣言値 (`num_inference_steps=50`, `iterations=30000`, `resolution=1024`, `num_views=N`, `num_samples=M` 等) を**変更しない**
3. 実行時間最小化 — 上記 1, 2 が **OOM 等のハードウェア制約で失敗した場合のみ** 削る (= OOM ladder に従う)

**MUST NOT** (= 時間短縮のみが動機の削減):

- "速いから" / "smoke として最小確認" を理由に `num_inference_steps` / `iterations` / `epochs` / `num_steps` を減らす
- 入力フレーム数 / multi-view 数 / sample 数を OOM 以外で減らす
- 解像度 (`--resolution` / `--img_size` / `--height` / `--width`) を OOM 以外で下げる
- `next_actions[]` に「論文デフォルト引数で再実行」を **`status=success` で** 高優先度として載せる (= デフォルトを使い切れていない自白 → status を `partial` に再考すべき。Step 1.7 参照)

**正当な縮小 (記録要)**:

- OOM ladder Step 2 (batch 半減) / Step 3 (解像度半減) — `attempts.tsv.intent` に「OOM で frame 数を半減 (Step 2)」のような**物理的根拠**を明記。`"to save time"` / `"for quick smoke"` は intent として禁止
- 著者が README / `examples/` で **明示的に** "quickstart" / "demo" として宣言している reduced-parameter 設定 — **論文デフォルト attempt と併存** (= デフォルト版も別 attempt で必ず走らせる)

**実行時間の扱い**:

- 推論 1 回が数分→1 時間でも、デフォルトで完走させる (= 待つ)
- training は `ScheduleWakeup` で待つ。8 時間でも問題ない (Phase 3.5 と同じ運用)
- 「時間がかかる」だけを理由に `status=partial` / `failed` にしない (= 失敗判定は claim 達成可否のみ、所要時間で決まらない)
- `experiment-loop` の tier 判定に**実行時間は影響しない** (= 数時間かかっても tier0/1/2 にならない)

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
