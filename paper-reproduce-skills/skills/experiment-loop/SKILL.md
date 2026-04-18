---
name: experiment-loop
description: autoresearch型の自律リトライループ。reports/attempts.tsv による永続ログ、git snapshot、3-Tier エラー分類、NEVER STOP 原則を実装。/reimplement の Phase 2/3 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Write Edit Grep
---

# experiment-loop: 自律リトライループ

karpathy/autoresearch 着想の自律実験ループ。`pixi install` が通り推論が走るまで、エラー診断→修正→再試行を自動で繰り返す。

## NEVER STOP 原則

- 環境構築に失敗しても止まらない — Tier 分類に従って自律的に修正・再試行
- 推論に失敗しても止まらない — OOM フォールバック → パラメータ変更 → CPU fallback
- 人間に「続けますか？」と聞かない
- 唯一の停止条件: 全 Phase 完了、または人間による手動停止

## reports/attempts.tsv

全試行を永続的に記録する TSV ファイル。`reports/` ディレクトリ配下に配置し、git には commit しない（`.gitignore` に `reports/attempts.tsv` を追加済み）。
エージェントは次の試行前にこのログを読み、同じ失敗を繰り返さない。

### フォーマット

```
attempt\tcommit\tphase\taction\tresult\terror_tier\terror_summary\tduration_s
```

### 列の定義

| 列 | 説明 |
|---|------|
| attempt | 試行番号 (1から連番) |
| commit | git short hash (7文字) |
| phase | `env-build` / `inference` / `verify` |
| action | この試行で導入した変更 の簡潔な説明（例: `bump_libc_2.31`, `add_c_cxx_compiler`, `patch_run_demo_headless`） |
| result | action の下流検証ステップ（`pixi install` や `python scripts/run_demo.py` 等）が成功したかどうか。`success` / `fail` / `crash` / `timeout` |
| error_tier | `tier0` / `tier1` / `tier2-config` / `tier2-hardware` / `tier3` / `-` |
| error_summary | 検証ステップが失敗したときの 1 行要約（失敗時のみ） |
| duration_s | 操作 (検証ステップを含む) にかかった秒数 |

### action と result の主語を揃える

**action は「変更」、result は「その変更で狙った検証ステップの成否」**。action と result の主語がずれるとログが読めなくなる。

- ❌ 悪い例: `action=headless_patch_run_demo, result=fail, error=triton_no_C_compiler`
  → 主語が曖昧。headless patch 自体は成功しているのに fail と記録されている。
- ✅ 良い例: `action=patch_run_demo_headless, result=success, duration_s=5`（patch して demo 実行、demo が CUDA error で失敗したら別行として `action=add_c_cxx_compiler, result=success, duration_s=15` を追加）
- ✅ 別解: 1 行にまとめたいなら action 側で「変更 + 検証」を合成する。`action=headless_patch_and_run_demo, result=fail, error=triton_no_C_compiler` のように 1 つの試行として明示する（ただしこの場合 headless patch 自体は commit 済みなので次の reset で消える点に注意）。

**原則:** 変更と検証をセットにした 1 試行 = 1 行。次の試行は前の失敗を踏まえた別の変更を加えて新しい行を作る。同じコミット SHA を複数行で共有しない。

### ログ記録の実装

**CRITICAL: 成功・失敗を問わず、すべての試行を reports/attempts.tsv に記録すること。記録漏れは禁止。**

各試行は以下の3ステップで記録する。ステップ1と3は省略不可:

```bash
# ステップ1: 試行開始前に必ず実行（省略禁止）
START_TIME=$(date +%s)

# ステップ2: 操作実行（pixi install, 推論 等）

# ステップ3: 操作完了後に必ず実行（成功でも失敗でも省略禁止）
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
COMMIT=$(git rev-parse --short HEAD)
echo -e "${ATTEMPT}\t${COMMIT}\t${PHASE}\t${ACTION}\t${RESULT}\t${TIER}\t${SUMMARY}\t${DURATION}" >> reports/attempts.tsv
```

**よくあるミス（してはいけない）:**
- 失敗した試行をログせずに次の試行に進む → 禁止。失敗もログしてから git reset する
- duration_s を 0 や空で埋める → 禁止。必ず START_TIME/END_TIME で実測する
- reports/report.html の試行数と reports/attempts.tsv の行数が一致しない → 禁止。reports/report.html は reports/attempts.tsv から生成する
- **警告だけで修正コミットを作る → 禁止**。`pixi install` / `pixi run` の exit code が 0 以外でない限り試行として扱わない。`iJIT_NotifyEvent` のような harmless warning を追いかけて pixi.toml を書き換えない（無駄な試行の典型）。

## Git-based State Management

### 試行前: スナップショット保存

```bash
git add pixi.toml pyproject.toml
git commit -m "attempt #${n}: ${action_description}"
```

### 成功時: advance

そのまま進む。branch tip が常に「最も進んだ正常状態」を表す。

### 失敗時: reset

**Phase 2（環境構築）での reset:**
```bash
git reset --hard HEAD~1
```
pixi.toml が直前の正常状態に戻る。`reports/attempts.tsv` は git 管理外なので消えない。

**Phase 3（推論実行）での reset — 安全な部分リセット:**

推論フェーズではスクリプトやコマンドライン引数の変更が主。`git reset --hard` だとダウンロード済みモデルファイル（gitignore 対象外の場合）やその他の作業ファイルも失われるリスクがある。

より安全な方法:
```bash
# pixi.toml とスクリプト変更のみを戻す（他のファイルは保持）
git checkout HEAD~1 -- pixi.toml
git checkout HEAD~1 -- {changed_script}
git reset HEAD~1
```

ただし、Phase 2 と統一して `git reset --hard HEAD~1` を使う場合は、モデルファイル等が `.gitignore` に含まれていることを事前に確認する。

## 4-Tier エラー分類

### Tier 0: Pre-flight Validation

環境を構築し始める前に 10 秒で直せるもの。`/reimplement` の Phase 0 で検出。Tier 0 を踏んだ場合は attempt 番号を消費せずに修正して再開する。

| エラー例 | 修正 |
|---------|------|
| `Author identity unknown` (git commit 時) | `git config user.email/name` を設定 |
| pixi.toml 構文エラー (`index=` 未定義など) | `pixi install --dry-run` で事前検出 |
| `Permission denied` on `/home/claude/.cache/...` | 書き込み可能な代替パスを env var で指定 |
| CUDA↔PyTorch 非互換 (matrix 違反) | cuda-dependency-resolver の matrix を参照 |
| ネットワーク到達不可 (pypi/huggingface) | `curl --head` で事前確認 |

### Tier 1: Trivial Fix（自動修正して即リトライ）

数秒で修正できる軽微なエラー。

| エラー例 | 自動修正 |
|---------|---------|
| `ModuleNotFoundError: lpips` | `pixi add --pypi lpips` して再実行 |
| `No module named 'cv2'` | `pixi add --pypi opencv-python-headless` |
| `FileNotFoundError` (モデルファイル) | ダウンロードコマンドを実行 |
| `ImportError: cannot import name ...` | バージョンを調整して再インストール |

### Tier 2-config: 設定変更で解決可能

pixi.toml / コマンドライン引数 / 環境変数の変更で直る。

| エラー例 | 戦略変更 |
|---------|---------|
| solver conflict (defaults 混入) | defaults チャンネル除去 → 再構築 |
| torch wheel が見つからない | PyPI index URL を修正 or CUDA バージョン変更 |
| PEP517 build failure | no-build-isolation に追加 → 再構築 |
| submodule のビルドエラー | git+commit hash 方式に切り替え |
| gcc version mismatch | `pixi add gcc=11 gxx=11` 追加 |
| 学習専用 dep が必須扱い | 推論に不要なら pixi.toml から外す |

### Tier 2-hardware: ハードウェア制約で縮小が必要

物理的リソース不足。パラメータを小さくして通す。

| エラー例 | 戦略 |
|---------|------|
| GPU OOM | OOM ladder (下記、Step 5 まで必ず試す) |
| Host RAM OOM (SIGKILL / RC=137) | batch/num_frames 縮小 → fp16 → CPU fallback |
| GPU compute capability 不足 | 低い精度の fallback or CPU fallback |

### Tier 3: Fundamental Rethink（根本的再検討）

現在のアプローチでは解決不可能。**Tier 2-hardware で OOM ladder の Step 5 (CPU fallback) を実行してから でないと Tier 3 に昇格させない。**

| エラー例 | 対応 |
|---------|------|
| hardware 非互換 (Step 5 含め全段階失敗) | レポートに Ampere+/24GB VRAM 要求を明記 |
| private repo / 認証必要 | 手動介入指示をレポートに記載 |
| 同じ Tier 2-config が 10 回失敗 | Type 変更を試行（例: A → B） |
| 原因不明のセグフォ | エラーレポートを出力 |

## エラー分類の判定ロジック

### 環境構築フェーズ (phase = env-build)

```
エラーメッセージを読む
  ├─ git identity / cache perm / pixi.toml syntax → Tier 0
  ├─ ModuleNotFoundError / ImportError → Tier 1
  ├─ solver conflict / build failure / wheel not found → Tier 2-config
  ├─ SegmentationFault → Tier 3
  ├─ 認証エラー / Permission denied → Tier 3
  └─ 同じ Tier 2-config が 10 回以上 → Tier 3 に昇格
```

### 推論実行フェーズ (phase = inference)

```
エラーメッセージを読む
  ├─ ModuleNotFoundError / FileNotFoundError (モデル/データ) → Tier 1
  ├─ cv2.error: display / matplotlib GUI / open3d visualization → Tier 1 (headless patch)
  ├─ ImportError: cannot import name → Tier 1
  ├─ CUDA out of memory / CUDA error → Tier 2-hardware (OOM ladder)
  ├─ Host RAM OOM / SIGKILL (RC=137) → Tier 2-hardware
  ├─ 入力ファイルが見つからない → Tier 2-config (パス修正 or サンプル作成)
  ├─ SegmentationFault → Tier 3
  ├─ 認証エラー (API key, token) → Tier 3
  ├─ データセットが非公開 / 巨大 → Tier 3
  └─ Tier 2-hardware が Step 5 まで全滅 → Tier 3 に昇格
```

### OOM ladder (Tier 2-hardware 専用、Step 5 必須)

GPU/CPU メモリ不足時の段階的対策。**各ステップで失敗したら必ず次へ進む。Step 5 (CPU fallback) を飛ばして Tier 3 に昇格させてはいけない。**

```
Step 1: torch.cuda.empty_cache() を推論前に挿入
Step 2: batch_size / num_frames を半減
Step 3: 入力解像度を半減 (--resolution, --img_size, --height/--width)
Step 4: with torch.no_grad() + torch.cuda.amp.autocast() を適用
Step 5: CPU fallback — CUDA_VISIBLE_DEVICES="" pixi run python ...
        (必須: Step 4 が 2 回失敗したら自動的に Step 5 を実行する)
        CPU で動いたら Tier 2-hardware 成功、report に「CPU-only fallback」として記録
        Step 5 も OOM / RC=137 なら Tier 3
```

### Headless 環境対策 (Tier 1 詳細)

Docker image に `/etc/headless_patches/headless_patch.py` が事前配置されている。**これが存在する場合は優先して使う**。以下のテンプレートは参照用・fallback 用。

Docker コンテナ内での GUI 関連エラーの自動修正:

```python
# cv2 の GUI 関数をモック
import cv2
cv2.imshow = lambda *a, **kw: None
cv2.waitKey = lambda *a, **kw: 0
cv2.destroyAllWindows = lambda: None
cv2.namedWindow = lambda *a, **kw: None

# matplotlib を非 GUI バックエンドに
import matplotlib
matplotlib.use('Agg')

# open3d の可視化をモック
import open3d as o3d
if hasattr(o3d, 'visualization'):
    o3d.visualization.draw_geometries = lambda *a, **kw: None
```

ラッパースクリプトとして `_headless_patch.py` を作成し、対象スクリプトの先頭で `exec(open('_headless_patch.py').read())` するか、`pixi run python -c "exec(open('_headless_patch.py').read()); exec(open('{script}').read())"` で実行。

## ループの全体構造

```
attempt = 0
while not succeeded:
    attempt += 1

    # 1. START_TIME=$(date +%s)  ← 省略禁止
    # 2. reports/attempts.tsv を読んで過去の失敗を確認
    # 3. 修正方針を決定（過去の失敗と同じことはしない）
    # 4. pixi.toml を修正
    # 5. git commit (スナップショット)
    # 6. pixi install 実行
    # 7. END_TIME=$(date +%s) && DURATION 計算  ← 省略禁止
    # 8. reports/attempts.tsv にログ追記  ← 成功でも失敗でも省略禁止
    # 9. 結果判定
    #    成功 → 環境検証 → Phase 3 へ
    #    失敗 → Tier 分類 → 修正 → git reset → continue
```
