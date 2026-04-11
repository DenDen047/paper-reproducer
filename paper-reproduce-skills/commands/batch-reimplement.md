---
description: 複数リポジトリを pueue で連続実行する。repos.txt にリポジトリ URL を1行1つ記載。
allowed-tools: Bash Read Write Edit Glob Grep
---

# /batch-reimplement — 複数リポジトリ連続再現

repos.txt（CWD に配置）のリポジトリ URL を順番に clone → `/reimplement` を実行する。
pueue でタスクキューを管理し、NEVER STOP で連続処理する。

## 前提条件

- CWD に `repos.txt` が存在する（1行1URL）
- Docker コンテナ内で実行（pueue がインストール済み）
- `ANTHROPIC_API_KEY` が環境変数に設定済み

## repos.txt フォーマット

```
https://github.com/user/repo1.git
https://github.com/user/repo2.git
https://github.com/user/repo3.git
```

空行と `#` で始まる行は無視する。

## 実行フロー

```bash
# 1. pueue デーモンを起動
pueued -d

# 2. repos.txt を読み込み
REPOS=$(grep -v '^#' repos.txt | grep -v '^$')

# 3. 結果ディレクトリを作成
RESULTS_DIR="${RESULTS_DIR:-/results}"
mkdir -p "$RESULTS_DIR"

# 4. 各リポジトリをタスクキューに登録（逐次実行: parallel=1）
pueue parallel 1
for url in $REPOS; do
  REPO_NAME=$(basename "$url" .git)
  pueue add -- bash -c "
    cd /workspace &&
    git clone '$url' '$REPO_NAME' &&
    cd '$REPO_NAME' &&
    claude --dangerously-skip-permissions \
      --plugin-dir /paper-reproduce-skills \
      --print \
      --prompt '/reimplement' &&
    mkdir -p '$RESULTS_DIR/$REPO_NAME' &&
    cp -rf reports '$RESULTS_DIR/$REPO_NAME/' 2>/dev/null
  "
done

# 5. 全タスク完了まで待機
pueue wait

# 6. サマリー生成
pueue status
```

## 結果の永続化

各リポジトリの `reports/` ディレクトリを丸ごと `$RESULTS_DIR/{repo_name}/reports/` にコピーする:

```
/results/
├── repo1/
│   └── reports/
│       ├── report.json
│       ├── report.html
│       ├── attempts.tsv
│       └── analysis.json
├── repo2/
│   └── reports/
│       └── ...
└── summary.json  ← 全リポジトリの集約レポート
```

## summary.json 生成

全リポジトリの `reports/report.json` を集約:

```json
{
  "timestamp": "ISO 8601",
  "total_repos": 3,
  "success": 2,
  "partial": 1,
  "failed": 0,
  "total_attempts": 15,
  "total_duration_s": 3600,
  "repos": [
    {
      "repo_name": "repo1",
      "status": "success",
      "dep_type": "B1",
      "attempts": 3,
      "duration_s": 120
    }
  ]
}
```

## Docker 実行例

```bash
# repos.txt を含むディレクトリから実行
docker run --gpus all \
  -v $(pwd):/workspace \
  -v pixi-cache:/home/claude/.cache/rattler \
  -v $(pwd)/results:/results \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  paper-reproduce \
  --print --prompt "/batch-reimplement"
```
