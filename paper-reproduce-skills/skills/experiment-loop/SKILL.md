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
| intent | この試行を打った理由を 1-2 文で記述（最大 200 字、単一行、タブ禁止） |
| result | `success` / `failed` / `crashed` / `timed_out` のみ（過去形統一）。装飾（`success(dry-run)` 等）は `error_summary` へ |
| error_tier | `tier0` / `tier1` / `tier2-config` / `tier2-hardware` / `tier3` / `-` のみ。`1` / `T1` / `Tier 1` / 空文字 禁止 |
| error_summary | 失敗時の 1 行要約 |
| duration_s | 実測秒数（START_TIME/END_TIME から算出） |

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

```bash
# 試行開始（省略禁止）
START_TIME=$(date +%s)
INTENT="..."  # 1-2 文で動機を記述。空 / 未設定は Tier 0 違反

# 操作実行

# 試行完了（成功・失敗問わず省略禁止）
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
COMMIT=$(git rev-parse --short HEAD)
echo -e "${ATTEMPT}\t${COMMIT}\t${PHASE}\t${ACTION}\t${INTENT}\t${RESULT}\t${TIER}\t${SUMMARY}\t${DURATION}" >> reports/attempts.tsv
```

### MUST NOT

- 失敗試行を記録せずに次へ進む
- duration_s を 0 / 空で埋める
- intent を空 / 未設定で記録する
- intent にタブ / 改行を含める（TSV 破壊）
- `result` の非正規値（`fail` / `partial` / 装飾付き `success(...)`。正規形は `success` / `failed` / `crashed` / `timed_out`）
- `error_tier` の非正規値（`1` / `T1` / `Tier 1` / 空。正規形は `tier0`–`tier3` / `tier2-config` / `tier2-hardware` / `-`）
- `phase` の非正規値（`2` / `Phase2` / `env-build`。正規形は `phase0`–`phase4`）
- `report.html` の試行数と `attempts.tsv` の行数を不一致にする
- exit code 0 の harmless warning（`iJIT_NotifyEvent` 等）を追って pixi.toml を書き換える

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
    # 8. attempts.tsv にログ追記（成功・失敗問わず）← 省略禁止
    # 9. 結果判定
    #    成功 → 次 Phase
    #    失敗 → Tier 分類 → 修正 → git reset → continue
```
