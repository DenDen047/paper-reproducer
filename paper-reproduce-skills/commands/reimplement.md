---
description: CV論文のGitHubリポジトリを全自動再現する。CWD=clone済みリポジトリで実行。
allowed-tools: Bash Read Write Edit Glob Grep Agent
---

# /reimplement — 論文リポジトリ全自動再現コマンド

あなたは CV 論文の GitHub リポジトリを Pixi 環境で全自動再現するエージェントです。
以下の Phase を順番に実行してください。**NEVER STOP**: 人間に「続けますか？」と聞かない。失敗しても自律的にリトライし続ける。手動停止されるまで止まらない。

---

## Phase 0: Initialize

1. `git status` で CWD が git リポジトリであることを確認
2. `git stash` で未コミット変更を退避（あれば）
3. リポジトリ名・URL を `git remote -v` から自動検出
4. `git submodule status` で submodule の有無を確認
5. attempts.tsv を初期化（ヘッダー行のみ書き込み）:
   ```
   attempt\tcommit\tphase\taction\tresult\terror_tier\terror_summary\tduration_s
   ```
6. `ls` で依存ファイル一覧を取得（Phase 1 の事前情報）
7. `.gitignore` に `attempts.tsv` を追加（git 管理外にする）

---

## Phase 1: リポジトリ解析

**repo-analyzer スキルを参照して実行。**

1. README.md を読む
2. 依存ファイルを特定し、6-Type 分類で判定（下記参照）
3. CUDA / PyTorch バージョンを特定
4. submodule を検出し、SSH URL は HTTPS に変換
5. C++/CUDA 拡張の有無を検出（no-build-isolation 候補）
6. defaults チャンネルの混入を検出
7. モデルダウンロード方法を特定
8. デモ/推論コマンドを特定
9. 難易度評価（easy/medium/hard）
10. 結果を `analysis.json` として出力

### 6-Type 分類（判定優先順位）

| 優先順位 | Type | 依存ファイル | 変換戦略 |
|---------|------|-------------|---------|
| 1 | A | environment.yml / conda.yaml | `pixi init --import` + Divide-and-Conquer |
| 2 | C | pyproject.toml | `pixi init --pyproject` |
| 3 | B | requirements.txt | `pixi init` + pypi-dependencies |
| 4 | E | setup.py / setup.cfg | deps 抽出 → pypi-dependencies (E3: requirements.txt 併存時は Type B にフォールバック) |
| 5 | D | Dockerfile のみ | 命令解析 → Type A/B に合流 |
| 6 | F | 依存ファイルなし | import 解析 + ソースマイニング |

### Type 判定フローチャート

```
environment.yml exists?
  YES → requirements.txt も存在? → YES: A3 / NO: submodule pip deps? → YES: A2 / NO: A1
  NO  → pyproject.toml exists?
    YES → [tool.poetry]? → YES: C2 / NO: [tool.pdm]? → YES: C3 / NO: C1
    NO  → requirements.txt exists?
      YES → setup.py exists? → YES: B2 / NO: 複数req files? → YES: B3 / NO: B1
      NO  → setup.py/setup.cfg exists?
        YES → requirements.txt exists? → YES: E3 (→Type B) / NO: E1/E2
        NO  → Dockerfile exists?
          YES → pip in Dockerfile? → YES: D1 / conda? → YES: D2 / NO: D3
          NO  → F
```

### analysis.json のスキーマ

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

**pixi-env-builder スキルと cuda-dependency-resolver スキルを参照して実行。**

analysis.json の `dep_type` に基づいて変換戦略を選択し、pixi.toml を生成する。

### Type A (conda系) のフロー

- **A1**: `pixi init --import environment.yml` → defaults 除去 → `pixi install`
- **A2**: environment.yml から submodule 行を除去 → cleaned.yml を作成 → `pixi init --import cleaned.yml` → defaults 除去 → ベースで `pixi install` → submodule を1つずつ pypi-dependencies に追加 → no-build-isolation 設定 → 完了後 cleaned.yml を削除
- **A3**: A2 と同様 + requirements.txt の差分を pypi-deps に追加

### 共通処理（全 Type で適用する denkiwakame ルール）

1. **defaults チャンネル除去**: channels から "defaults" を削除
2. **CUDA 統一**: PyPI wheel の場合は cuda-toolkit、conda の場合は gcc/gxx も追加
3. **system-requirements.cuda 設定**: ホストドライバ要件の申告
4. **submodule → pypi-dependencies 変換**: editable install + no-build-isolation
5. **Divide-and-Conquer**: ベース deps だけで通す → submodule を1つずつ追加
6. **gcc/gxx を pixi 管理下に**: nvidia channel 使用時は必須

### Experiment Loop（NEVER STOP）

**experiment-loop スキルを参照して実行。**

```
while not succeeded:
  1. START_TIME=$(date +%s)  ← 省略禁止
  2. pixi.toml を生成/修正
  3. git add pixi.toml && git commit -m "attempt #{n}: {action}"
  4. pixi install 2>&1 | tee build.log
  5. END_TIME=$(date +%s) && DURATION=$((END_TIME - START_TIME))  ← 省略禁止
  6. attempts.tsv にログ追記（成功でも失敗でも必ず記録）  ← 省略禁止
  7. 結果判定:
     成功 → advance + 環境検証 (python -c "import torch; print(torch.cuda.is_available())")
     失敗 → diagnose + classify:
       Tier 1 (Trivial Fix): auto-fix → retry
       Tier 2 (Strategy Change): 戦略変更 → rebuild
       Tier 3 (Fundamental Rethink): Type変更 or report
  8. 失敗時: git reset --hard HEAD~1
```

**CRITICAL: ステップ1, 5, 6 は成功・失敗を問わず毎回必ず実行する。attempts.tsv への記録漏れは禁止。**

---

## Phase 3: 推論実行

1. モデルダウンロード（analysis.json の model_download に基づく）
2. デモ/推論スクリプト実行: `pixi run python {demo_command}`
3. 失敗時の段階的フォールバック:
   - Tier 1: missing module → `pixi add --pypi {module}`
   - Tier 2: OOM → batch size 削減 → 解像度削減 → CPU fallback
   - Tier 3: 根本的問題 → レポートに記載
4. attempts.tsv にログ追記

---

## Phase 4: レポート生成

1. 中間ファイルのクリーンアップ: cleaned.yml 等の一時ファイルを削除
2. `report.json` 生成（機械可読）:
   ```json
   {
     "repo_name": "string",
     "repo_url": "string",
     "status": "success|partial|failed",
     "dep_type": "string",
     "total_attempts": "number",
     "duration_total_s": "number",
     "pixi_toml_hash": "string",
     "inference_output": "string|null",
     "errors": ["string"]
   }
   ```
   **status の判定基準:**
   - `success`: pixi install 成功 + 推論実行成功（出力ファイルが生成された）
   - `partial`: pixi install 成功 + 推論未実行（データセット不在等）、または pixi install 成功 + 推論一部成功
   - `failed`: pixi install 失敗、または推論が根本的に動作しない
3. `report.html` 生成（目視確認用）— **必ず attempts.tsv を読み込んで試行履歴テーブルを生成すること**。report.html の試行数と attempts.tsv の行数は一致しなければならない。
4. 最終状態の pixi.toml + pixi.lock を保持

---

## 核心原則

### NEVER STOP
- 環境構築に失敗しても止まらない — Tier 分類に従って自律的に修正・再試行
- 推論に失敗しても止まらない — OOM フォールバック → パラメータ変更 → CPU fallback
- 唯一の停止条件: 全 Phase 完了、または人間による手動停止

### denkiwakame ワークフロー準拠
- **Divide-and-Conquer**: submodule は最初に除外し、ベース構築後に1つずつ追加
- **no-build-isolation**: PEP517 違反の submodule (C++/CUDA 拡張) に必須
- **CUDA は1つに統一**: wheel/conda/docker/host の4つが混在するサバンナを整理
- **defaults チャンネル除去**: miniconda 由来で混入しがちだが有償かつ不要
- **conda-forge を基本チャンネル**: ただし元 repo が conda pytorch を使う場合は pytorch/nvidia チャンネルも許容
- **gcc/gxx も pixi 管理下に**: nvidia channel の CUDA では gcc/g++ が外側から見えない
- **system-requirements.cuda**: ホストドライバ要件の申告であり、pixi 環境内の CUDA バージョンとは別物
