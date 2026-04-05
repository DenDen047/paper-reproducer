---
name: experiment-loop
description: autoresearch型の自律リトライループ。attempts.tsv による永続ログ、git snapshot、3-Tier エラー分類、NEVER STOP 原則を実装。/reimplement の Phase 2/3 で自動参照される。
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

## attempts.tsv

全試行を永続的に記録する TSV ファイル。git には commit しない。
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
| action | 実行した操作の簡潔な説明 |
| result | `success` / `fail` / `crash` / `timeout` |
| error_tier | `tier1` / `tier2` / `tier3` / `-` |
| error_summary | エラーの1行要約 (失敗時のみ) |
| duration_s | 操作にかかった秒数 |

### ログ記録の実装

**CRITICAL: 成功・失敗を問わず、すべての試行を attempts.tsv に記録すること。記録漏れは禁止。**

各試行は以下の3ステップで記録する。ステップ1と3は省略不可:

```bash
# ステップ1: 試行開始前に必ず実行（省略禁止）
START_TIME=$(date +%s)

# ステップ2: 操作実行（pixi install, 推論 等）

# ステップ3: 操作完了後に必ず実行（成功でも失敗でも省略禁止）
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
COMMIT=$(git rev-parse --short HEAD)
echo -e "${ATTEMPT}\t${COMMIT}\t${PHASE}\t${ACTION}\t${RESULT}\t${TIER}\t${SUMMARY}\t${DURATION}" >> attempts.tsv
```

**よくあるミス（してはいけない）:**
- 失敗した試行をログせずに次の試行に進む → 禁止。失敗もログしてから git reset する
- duration_s を 0 や空で埋める → 禁止。必ず START_TIME/END_TIME で実測する
- report.html の試行数と attempts.tsv の行数が一致しない → 禁止。report.html は attempts.tsv から生成する

## Git-based State Management

### 試行前: スナップショット保存

```bash
git add pixi.toml pyproject.toml
git commit -m "attempt #${n}: ${action_description}"
```

### 成功時: advance

そのまま進む。branch tip が常に「最も進んだ正常状態」を表す。

### 失敗時: reset

```bash
git reset --hard HEAD~1
```

pixi.toml が直前の正常状態に戻る。attempts.tsv は git 管理外なので消えない。

## 3-Tier エラー分類

### Tier 1: Trivial Fix（自動修正して即リトライ）

数秒で修正できる軽微なエラー。

| エラー例 | 自動修正 |
|---------|---------|
| `ModuleNotFoundError: lpips` | `pixi add --pypi lpips` して再実行 |
| `No module named 'cv2'` | `pixi add --pypi opencv-python-headless` |
| pixi.toml の typo | 修正して `pixi install` 再実行 |
| `FileNotFoundError` (モデルファイル) | ダウンロードコマンドを実行 |
| `ImportError: cannot import name ...` | バージョンを調整して再インストール |

### Tier 2: Strategy Change（戦略変更して再構築）

根本的なアプローチの変更が必要。

| エラー例 | 戦略変更 |
|---------|---------|
| solver conflict (defaults 混入) | defaults チャンネル除去 → 再構築 |
| torch wheel が見つからない | PyPI index URL を修正 or CUDA バージョン変更 |
| PEP517 build failure | no-build-isolation に追加 → 再構築 |
| submodule のビルドエラー | git+commit hash 方式に切り替え or バージョン固定 |
| gcc version mismatch | `pixi add gcc=11 gxx=11` 追加 |
| OOM (GPU メモリ不足) | batch size 削減 → 解像度削減 → CPU fallback |

### Tier 3: Fundamental Rethink（根本的再検討）

現在のアプローチでは解決不可能。

| エラー例 | 対応 |
|---------|------|
| hardware 非互換 (特定 GPU 専用) | CPU fallback or スキップを報告 |
| private repo の依存 (認証必要) | 手動介入指示をレポートに記載 |
| 10回以上の Tier 2 失敗 | Type 変更を試行（例: Type A → Type B に切り替え） |
| 原因不明のセグフォ | エラーレポートを出力 |

## エラー分類の判定ロジック

```
エラーメッセージを読む
  ├─ ModuleNotFoundError / ImportError → Tier 1
  ├─ FileNotFoundError (モデル/データ) → Tier 1
  ├─ SyntaxError in pixi.toml → Tier 1
  ├─ solver conflict / resolution error → Tier 2
  ├─ build failure (gcc/nvcc) → Tier 2
  ├─ OOM / CUDA out of memory → Tier 2
  ├─ wheel not found → Tier 2
  ├─ SegmentationFault → Tier 3
  ├─ 認証エラー / Permission denied → Tier 3
  └─ 同じ Tier 2 エラーが10回以上 → Tier 3 に昇格
```

## ループの全体構造

```
attempt = 0
while not succeeded:
    attempt += 1

    # 1. attempts.tsv を読んで過去の失敗を確認
    # 2. 修正方針を決定（過去の失敗と同じことはしない）
    # 3. pixi.toml を修正
    # 4. git commit (スナップショット)
    # 5. pixi install 実行
    # 6. 結果判定
    #    成功 → 環境検証 → Phase 3 へ
    #    失敗 → Tier 分類 → 修正 → git reset → continue
    # 7. attempts.tsv にログ追記
```
