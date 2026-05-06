---
name: experiment-loop
description: autoresearch型の自律リトライループ。reports/attempts.tsv による永続ログ、git snapshot、4-Tier エラー分類、NEVER STOP 原則を実装。/reimplement の Phase 2/3 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Write Edit Grep
---

# experiment-loop: 自律リトライループ

karpathy/autoresearch 着想。`pixi install` と推論が通るまで、診断→修正→再試行を自律反復する。

## NEVER STOP

- Tier 分類に従って修正・再試行を継続
- OOM は Step 5（CPU fallback）まで必ず試す
- 停止条件は全 Phase 完了または手動停止のみ
- 人間に確認しない

## reports/attempts.tsv

全試行の永続ログ。`.gitignore` 対象。次試行前に読み、同じ失敗を繰り返さない。

### フォーマット

```
attempt\tcommit\tphase\taction\tintent\tresult\terror_tier\terror_summary\tduration_s
```

| 列 | 内容 |
|---|---|
| attempt | 1 からの連番 |
| commit | git short hash (7 文字) |
| phase | `phase0`–`phase4` のみ（`commands/reimplement.md` の macro phase と一致）。試行発生は `phase2`/`phase3` のみ。`2` / `Phase2` / `env-build` 禁止 |
| action | 導入した変更（例: `bump_libc_2.31`、`add_c_cxx_compiler`） |
| intent | 試行の動機を 1-2 文で記述（最大 200 字、単一行、タブ禁止） |
| result | `success` / `failed` / `crashed` / `timed_out` のみ（過去形統一）。装飾（`success(dry-run)` 等）は `error_summary` へ |
| error_tier | `tier0` / `tier1` / `tier2-config` / `tier2-hardware` / `tier3` / `-` のみ。`1` / `T1` / `Tier 1` / 空文字 禁止 |
| error_summary | 失敗時の 1 行要約 |
| duration_s | `date +%s` 実測値のみ。手動見積もり禁止。長時間処理（DL / 学習）も START_TIME / END_TIME で囲う |

### action と result の主語

1 試行 = 1 変更 + 1 検証 = 1 行。action は「変更」、result は「その変更で狙った検証の成否」。

良い例: `action=patch_run_demo_headless, result=success` の次行で `action=add_c_cxx_compiler, result=success`。

悪い例:
- 主語ずれ: headless patch 成功を triton エラーで `result=failed` にする
- patch と検証を 1 行に合成: `action=headless_patch_and_run_demo` → 2 行に分割
- 複数変更を 1 action に詰める: `add_gcc_and_bump_torch` → 1 変更 1 行

同じ commit SHA を複数行で共有しない。

### intent の書き方

action が「何を変えたか」(snake_case ラベル) なのに対し、intent は「**なぜ**変えたか」を読者向けに 1-2 文の散文で書く。試行**開始前**に決定し、`INTENT="..."` として保持。空文字 / 未設定は Tier 0 違反。

良い例:
- `action=bump_libc_2.31, intent=open3d 0.19 が GLIBC 2.27 で起動できないため、conda 経由で libc=2.31 を導入して再試行`
- `action=add_c_cxx_compiler, intent=triton のソースビルドで gcc/g++ が不足。conda-forge から導入`
- `action=run_demo, intent=headless パッチ後の最初の推論検証。出力 PNG が生成されるか確認`

悪い例:
- 動機なし: `intent=add gcc11`（action のリネームに過ぎない）
- 結果を書く: `intent=open3d 起動成功、続いて triton で失敗`（観察は error_summary 側）
- 長すぎる: 200 字超 / 改行入り（テーブル列に収まらない）

### ログ記録

`date +%s` は操作の直前/直後に呼ぶ。後付け見積もり禁止

```bash
# 試行開始（省略禁止）
START_TIME=$(date +%s)
INTENT="..."  # 動機 1-2 文。空 / 未設定は Tier 0 違反

# 操作実行（DL・学習・推論など長時間処理もこの内側）

# 試行完了（成功・失敗問わず省略禁止）
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
COMMIT=$(git rev-parse --short HEAD)
echo -e "${ATTEMPT}\t${COMMIT}\t${PHASE}\t${ACTION}\t${INTENT}\t${RESULT}\t${TIER}\t${SUMMARY}\t${DURATION}" >> reports/attempts.tsv
```

長時間処理を別 attempt として独立記録するのは可。START_TIME 漏れは `git log --format=%at` で逆算補填。

### MUST NOT

- 失敗試行の記録省略
- duration_s の 0 / 空埋め
- duration_s の手動見積もり
- 長時間処理（DL / 学習）の START_TIME/END_TIME 外実行
- intent の空 / 未設定
- intent へのタブ / 改行混入（TSV 破壊）
- `result` の非正規値（`fail` / `partial` / 装飾付き `success(...)`。正規形は `success` / `failed` / `crashed` / `timed_out`）
- `error_tier` の非正規値（`1` / `T1` / `Tier 1` / 空。正規形は `tier0`–`tier3` / `tier2-config` / `tier2-hardware` / `-`）
- `phase` の非正規値（`2` / `Phase2` / `env-build`。正規形は `phase0`–`phase4`）
- `report.html` 試行数と `attempts.tsv` 行数の不一致
- harmless warning（exit 0 の `iJIT_NotifyEvent` 等）追跡による pixi.toml 改変

## Git-based State Management

### 試行前: スナップショット

```bash
git add pixi.toml pyproject.toml
git commit -m "attempt #${n}: ${action_description}"
```

### 成功: そのまま advance（branch tip が最新の正常状態）

### 失敗: reset

**Phase 2:**
```bash
git reset --hard HEAD~1
```
`reports/attempts.tsv` は git 管理外なので消えない。

**Phase 3（ダウンロード済みモデルを守る）:**
```bash
git checkout HEAD~1 -- pixi.toml
git checkout HEAD~1 -- {changed_script}
git reset HEAD~1
```
モデルファイルが `.gitignore` 済みなら Phase 2 と同じ `git reset --hard HEAD~1` で統一可。

## 4-Tier エラー分類

### Tier 0: Pre-flight Validation

10 秒で直せるもの。attempt 番号を消費せずに修正して再開。

| エラー | 修正 |
|---|---|
| `Author identity unknown` | `git config user.email/name` |
| pixi.toml 構文エラー | `pixi install --dry-run` で事前検出 |
| `Permission denied` on `$HOME/.cache` | env var で書き込み可能パスに逃がす |
| CUDA↔PyTorch 非互換 | cuda-dependency-resolver の matrix |
| pypi/huggingface 到達不可 | `curl --head` で事前確認 |

### Tier 1: Trivial Fix

数秒で自動修正して即リトライ。

| エラー | 修正 |
|---|---|
| `ModuleNotFoundError` | `pixi add --pypi {name}` |
| `No module named 'cv2'` | `pixi add --pypi opencv-python-headless` |
| `FileNotFoundError`（モデル） | ダウンロードコマンド実行 |
| `ImportError: cannot import name` | バージョン調整 |
| cv2/matplotlib/open3d の GUI 呼び出し | headless patch 適用 |

### Tier 2-config

pixi.toml / コマンド引数 / env var の変更で直る。

| エラー | 対処 |
|---|---|
| solver conflict（defaults 混入） | defaults チャンネル除去 |
| torch wheel 未発見 | PyPI index URL 修正 or CUDA 変更 |
| PEP517 build failure | `no-build-isolation` 追加 |
| submodule ビルドエラー | `git+commit_hash` 方式に切替 |
| gcc version mismatch | `pixi add gcc=11 gxx=11` |
| 学習専用 dep が必須扱い | 推論不要なら除去 |

### Tier 2-hardware

リソース不足または GPU アーキテクチャ非互換。OOM ladder / Arch Upgrade Ladder で対処。

| エラー | 対処 |
|---|---|
| GPU OOM | OOM ladder |
| Host RAM OOM (SIGKILL / RC=137) | batch/num_frames 縮小 → fp16 → CPU |
| `CUDA error: no kernel image is available` （ホスト GPU が新しすぎる） | Arch Upgrade Ladder |
| GPU が古すぎる（required SM > host SM） | CPU fallback（OOM ladder Step 5 相当） |

### Tier 3: Fundamental Rethink

**Tier 2-hardware の Step 5 まで試してからのみ昇格する。**

| エラー | 対応 |
|---|---|
| Step 5 含め全滅 | VRAM/Ampere+ 要求をレポートに明記 |
| private repo / 認証必要 | 手動介入指示をレポート |
| 同一 Tier 2-config が 10 回失敗 | Type 変更を試行（例: A→B） |
| 原因不明のセグフォ | エラーレポート出力 |
| **GDrive レート制限** ("but Gdown can't" + "domain administrator" 文言) | 24h cooldown 必要。`next_actions` に「{n} 時間後に gdown {file_id} -O {path} を再実行」を追加。**status は `data_acquisition_table[i].required_for_claims` で判定** (P2-B): 空 (= optional) → status=success 維持 / 非空 (= 必須) → `report.json.errors` に `blocked_external_rate_limit` を追加し status=partial 候補 |

## 判定フロー

### env-build

```
ログを読む
  ├─ git identity / cache perm / pixi.toml syntax → Tier 0
  ├─ ModuleNotFoundError / ImportError → Tier 1
  ├─ solver conflict / build failure / wheel not found → Tier 2-config
  ├─ SegmentationFault / 認証 / Permission denied → Tier 3
  └─ 同じ Tier 2-config が 10 回超 → Tier 3 昇格
```

### inference

```
ログを読む
  ├─ ModuleNotFoundError / FileNotFoundError → Tier 1
  ├─ cv2.error / matplotlib GUI / open3d visualization → Tier 1 (headless patch)
  ├─ CUDA OOM / Host RAM OOM (RC=137) → Tier 2-hardware (OOM ladder)
  ├─ CUDA error: no kernel image is available → Tier 2-hardware (Arch Upgrade Ladder)
  ├─ 入力パス不正 → Tier 2-config
  ├─ SegmentationFault / 認証 / 非公開データセット → Tier 3
  └─ OOM ladder / Arch Upgrade Ladder Step 4 まで全滅 → Tier 3 昇格
```

## データ取得失敗の分類 (P2-B)

`commands/reimplement.md` Phase 3 Step 1 (`data_acquisition_table` ベースの dataset DL) で発生する失敗を、`required_for_claims` の有無と組み合わせて分類する。

| 失敗種別 | 判定文字列 | tier / 扱い |
|---|---|---|
| HTTP 4xx / 5xx (transient) | `curl: (22)` / `404 Not Found` | tier1 (3 回まで自動 retry、URL の変動は README 代替リンクで補正) |
| GDrive レート制限 | `"but Gdown can't"` + `"domain administrator"` / `"too many users"` | tier3 (24h cooldown) |
| HF gated repo | `401 Unauthorized` / `Repository not found` 系 | tier3 (`gated` カテゴリ、`next_actions` に手動手順) |
| 認証必要 | `403` / login redirect | tier3 |

**status 維持判定** (P2-B 核心):

```python
# data_acquisition_table[i].required_for_claims が空 (= optional) なら status=success 維持
# 非空 (= 必須 dataset) なら blocked_external_rate_limit を errors[] に追加し partial 候補
required = entry.get("required_for_claims", [])
if not required:
    pass  # success 維持。reports/_blocked_optional.json に記録のみ
else:
    errors.append(f"blocked_external_rate_limit: {entry['name']} (required for {required})")
    # report.json.status の最終判定で partial になる候補
```

`experiment-loop` 内ではこの判定だけ行い、status の最終確定は Phase 4 Step 2 の集約ルールに委ねる。

## OOM ladder（Tier 2-hardware）

各 Step で失敗したら次へ進む。Step 5 を飛ばして Tier 3 に昇格させない。

```
Step 1: torch.cuda.empty_cache() を推論前に挿入
Step 2: batch_size / num_frames を半減
Step 3: 入力解像度を半減 (--resolution / --img_size / --height / --width)
Step 4: torch.no_grad() + torch.cuda.amp.autocast()
Step 5: CPU fallback — CUDA_VISIBLE_DEVICES="" pixi run python ...
        Step 4 が 2 回失敗したら自動的に Step 5
        CPU で動けば成功扱い、report に「CPU-only fallback」と記録
        Step 5 も OOM → Tier 3
```

## Arch Upgrade Ladder（Tier 2-hardware: GPU アーキテクチャ非互換）

`no kernel image` エラー時に使用。`gpu_arch_incompatible.recommended_torch/cuda` を起点とし、Step 4 まで試みてから Tier 3 昇格。

```
Step 1: pixi.toml の torch wheel を recommended_torch+cuda に更新 → pixi install
        新 torch が Python バージョン要件を上げる場合は python = "x.y.*" も同時に変更
Step 2: CUDA 拡張（gsplat / pointops 等）を新 cuda で再ビルド（install-* タスクを再実行）
Step 3: API 互換エラー → Tier 2-config で自動修正
        （torch.load weights_only 引数追加・deprecated import パス変更・設定フラグ切替など）
Step 4: CPU fallback（OOM ladder Step 5 相当）
        成功時は report に「CPU-only fallback: arch_upgrade_failed」を記録
        Step 4 も失敗 → Tier 3
```

多段ソースビルドが必要な依存（例: cumm → spconv の連鎖）は Tier 3 に達することがある。
Tier 3 時: `errors` に `gpu_arch_incompatible` を記載、`next_actions` に推奨 torch/cuda と依存非互換リストを記述。

## Headless 環境対策（Tier 1 詳細）

Docker image に `/etc/headless_patches/headless_patch.py` が事前配置されている。**存在すればこれを優先**。無い場合のみ以下を fallback として `_headless_patch.py` に書き出す:

```python
import cv2
cv2.imshow = lambda *a, **kw: None
cv2.waitKey = lambda *a, **kw: 0
cv2.destroyAllWindows = lambda: None
cv2.namedWindow = lambda *a, **kw: None

import matplotlib
matplotlib.use('Agg')

import open3d as o3d
if hasattr(o3d, 'visualization'):
    o3d.visualization.draw_geometries = lambda *a, **kw: None
```

対象スクリプトの先頭で `exec(open('_headless_patch.py').read())`、または `pixi run python -c "exec(open('_headless_patch.py').read()); exec(open('{script}').read())"`。

## ループ骨格

```
attempt = 0
while not succeeded:
    attempt += 1
    # 1. START_TIME=$(date +%s)               ← 省略禁止
    # 2. attempts.tsv を読み過去失敗を確認
    # 3. 修正方針決定（過去と同じ失敗を繰り返さない）
    # 4. pixi.toml / スクリプト修正
    # 5. git commit
    # 6. pixi install / 推論実行
    # 7. END_TIME & DURATION 算出            ← 省略禁止
    # 8. (失敗時のみ) Tier が tier2-config / tier2-hardware / tier3 なら
    #     scripts/search_github_issues.sh を 1 回呼び、関連 Issue 番号を error_summary に付記
    # 9. attempts.tsv にログ追記（成功・失敗問わず）← 省略禁止
    #10. 結果判定
    #    成功 → 次 Phase
    #    失敗 → Tier 分類 → 修正 → git reset → continue
```

## Long-running training の fail-fast (Phase 3.5 用、P3-C)

30k iter の training を最後まで回した後で「実は loss が iter 5000 から NaN だった」と気づくのは時間損失が大きい。fail-fast は **「再現を諦めて停止する」ではなく、「無駄な計算を切って即次 attempt を起動する」** ためにある。本システムのコンセプト「時間制限なし・全自動・claim 達成まで」を保ちつつ、明らかに失敗確定の training を回し続けるのを避ける。

watcher の `abort_signal_file` の中身 (`tier1` / `tier2-config` / `tier2-hardware`) を `attempts.tsv` の error_tier に直接転記し、experiment-loop はそれに従って次 attempt の action を決める。**training を SIGTERM するのは watcher が指示したときだけ** (= 自然完走したら eval / claim verify に進む)。

### 起動

`scripts/training_watcher.py` を background で起動し、training プロセスの実 PID と期待 artifact パスを渡す:

```bash
TRAIN_LOG=reports/_train.log
pixi run python train.py ... > "$TRAIN_LOG" 2>&1 &
TRAIN_PID=$!
echo "$TRAIN_PID" > /tmp/_train.pid

pixi run python /paper-reproduce-skills/scripts/training_watcher.py \
  --pid "$TRAIN_PID" \
  --log "$TRAIN_LOG" \
  --metrics reports/training_metrics.json \
  --checkpoint-dir output/exp/point_cloud \
  --expected-first-dump-iter 7500 \
  --abort-signal-file /tmp/_train.abort &

# training が終わるまで待つ。watcher が abort signal を立てたら kill。
while kill -0 "$TRAIN_PID" 2>/dev/null; do
    if [ -f /tmp/_train.abort ]; then
        kill -SIGTERM "$TRAIN_PID"; sleep 5; kill -SIGKILL "$TRAIN_PID" 2>/dev/null
        break
    fi
    sleep 30
done
```

### 検知ルール (training 開始から 5 分経過後、30 秒間隔で評価)

| 検知 | tier 分類 | 次 attempt の action |
|---|---|---|
| loss が NaN/Inf に **3 回連続** | tier2-config | lr 半減 + amp 切替 + gradient clip (`add_grad_clip` / `halve_lr`) |
| OOM (RC=137 / `out of memory`) 1 回 | tier2-hardware | gradient checkpointing / batch size 半減 (`enable_grad_ckpt` / `halve_batch`) |
| 期待 artifact 未生成 (`last_iter > expected_first_dump_iter` かつ `checkpoint-dir` に 1 個も chkpnt なし) | tier1 | 出力パス設定修正 (`fix_output_path`) |
| it/s が直近 5 分平均から 50% 以下が 10 分継続 | warning | 停止せず `training_metrics.json.warnings[]` に記録 |
| eta が想定時刻を超過 | warning | 停止しない (budget 上限なし) |

### Phase 3.5 完走後の eval 失敗との関係

- **Phase 3.5 完走** → P0-C の `claims_verification` で status を判定。`missed` が出ても再 training しない (人間判断に委ねる)
- **training 途中の機械的検知** (NaN, OOM, artifact 不生成) → 本セクションで即修正

watcher が abort_signal を立てた場合のみ training を SIGTERM、tier 分類を `attempts.tsv` に記録、`experiment-loop` の next attempt を発火する。

### Resume 対応

OOM / preemption で training が中断し、checkpoint があれば `analysis.json.training_recovery.resume_arg` を付けて **1 回だけ自動再開**する (Tier 1 の特殊形)。再開でも失敗したら通常の Tier 分類へ:

```bash
# attempts.tsv の前行が training の OOM/crash で、checkpoint dir に chkpnt が存在
LATEST_CKPT=$(ls output/exp/chkpnt*.pth 2>/dev/null | tail -1)
if [ -n "$LATEST_CKPT" ] && [ "$RESUME_ATTEMPTED" != "1" ]; then
    RESUME_ARG=$(jq -r '.training_recovery.resume_arg // empty' reports/analysis.json | sed "s|<exp>|$EXP_NAME|g")
    pixi run python train.py ... $RESUME_ARG  # 1 回だけ
    RESUME_ATTEMPTED=1
fi
```

`training_recovery` が `null` の場合は resume せず通常の Tier 分類へ。

## GitHub Issue / PR 即時検索（失敗時のみ）

`tier2-config` / `tier2-hardware` / `tier3` の失敗が出た瞬間に、同リポジトリの既存 Issue / PR を検索して `attempts.tsv` の `error_summary` 列に `[Issue #N]` プレフィックスを付ける。`tier0` / `tier1` は数秒で直る軽症なのでスキップ (rate-limit 配慮)。

```bash
GITHUB_SLUG=$(jq -r '.github_slug // empty' reports/analysis.json)

case "$TIER" in
  tier0|tier1) ;;
  *)
    if [ -n "$GITHUB_SLUG" ]; then
      # 先頭 6 単語を gh の検索キーに (長文 error は精度を下げる)
      ERR_KEY=$(echo "$ERROR_SUMMARY" | tr -s ' ' | cut -d' ' -f1-6)
      bash /paper-reproduce-skills/scripts/search_github_issues.sh \
        --repo "$GITHUB_SLUG" --kind issues --limit 3 \
        --query "$ERR_KEY" \
        --output "reports/_gh_attempt_${ATTEMPT}.json" || true
      RELATED=$(jq -r '.results[0:2] | map("#\(.number)") | join(",")' \
                  "reports/_gh_attempt_${ATTEMPT}.json" 2>/dev/null || echo "")
      if [ -n "$RELATED" ]; then
        ERROR_SUMMARY="[$RELATED] $ERROR_SUMMARY"
      fi
    fi
    ;;
esac
```

`scripts/search_github_issues.sh` は `gh` 未インストール / 未認証 / rate-limit のいずれの場合も exit 0 で空 `results: []` を返すため、このループは決して止まらない。`error_summary` 列内へのプレフィックス追記なので **`attempts.tsv` の 9 列構造は壊さない** (HTML テーブルとの行数 assertion も無傷)。

中間 JSON `reports/_gh_attempt_*.json` は Phase 4 Step 1 の中間ファイル削除でクリーンアップする。
