---
name: repo-analyzer
description: リポジトリの依存管理方式を解析し、6-Type分類を行い reports/analysis.json を生成する。/reimplement の Phase 1 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Glob Grep Write
---

# repo-analyzer: リポジトリ解析 + 6-Type 判定

CWD のリポジトリを解析し、Pixi 環境構築に必要な情報を `reports/analysis.json` として出力する。`reports/` ディレクトリは `/reimplement` の Phase 0 で作成済み。

## 解析手順

### Step 1: 依存ファイルの検出

以下のファイルを検索する:

```bash
# conda 系
ls environment.yml environment.yaml conda_env.yml conda.yaml 2>/dev/null

# pip 系
ls requirements*.txt 2>/dev/null

# modern Python
ls pyproject.toml 2>/dev/null

# legacy
ls setup.py setup.cfg 2>/dev/null

# Docker
ls Dockerfile Dockerfile.* docker/Dockerfile docker/*.Dockerfile 2>/dev/null
find . -maxdepth 3 -iname "Dockerfile*" 2>/dev/null
```

検索したパス一覧を `analysis.json.dockerfile_search_note` に記録する。

### Step 2: defaults チャンネル検出

environment.yml / conda.yaml が存在する場合、`channels:` セクションに `defaults` が含まれているかを確認する。検出した場合は `reports/analysis.json` の `pixi_strategy` に記録し、Phase 2 で除去する。

### Step 3: 6-Type 判定

判定優先順位に従い、最も情報量の多い依存ファイルで Type を決定する。

**Type A (conda系)**: environment.yml / conda.yaml が存在
- A1: environment.yml が完璧（submodule の pip deps 行がない）
- A2: environment.yml に submodule の pip deps 行がある、または submodule が存在する
- A3: environment.yml + requirements.txt が共存

**Type C (pyproject.toml)**: environment.yml がなく pyproject.toml が存在
- C1: [build-system] が setuptools / hatch / flit
- C2: [tool.poetry] セクションが存在
- C3: [tool.pdm] セクションが存在

**Type B (requirements.txt)**: environment.yml / pyproject.toml がなく requirements.txt が存在
- B1: requirements.txt のみ
- B2: requirements.txt + setup.py
- B3: 複数の requirements_*.txt

**Type E (setup.py/setup.cfg)**: 上記がなく setup.py / setup.cfg が存在
- E1: setup.py
- E2: setup.cfg
- E3: setup.py + requirements.txt が併存 → requirements.txt 優先 (Type B にフォールバック)

**Type D (Dockerfile)**: 他の依存ファイルがなく Dockerfile のみ
- D1: Dockerfile 内に pip install
- D2: Dockerfile 内に conda install
- D3: apt-get + pip 混在

**Type F**: 依存ファイルが一切ない

### Step 4: CUDA / PyTorch バージョン特定

以下の情報源から CUDA / PyTorch のバージョンを推定:

1. environment.yml / requirements.txt 内の torch バージョン指定
2. Dockerfile の FROM イメージ（例: `nvidia/cuda:12.1.0-devel-ubuntu22.04`）
3. README.md の記載
4. setup.py / pyproject.toml 内の依存
5. ソースコード中のバージョンチェック（例: `assert torch.cuda.is_available()`）

**CUDA バージョンが複数検出された場合**: 最も明示的な指定（environment.yml > Dockerfile > README）を優先。

### Step 5: submodule 検出 (Type 判定の前に必須)

submodule の有無と性質は Type 判定 (Step 3) と `pixi_strategy.needs_divide_and_conquer` に直接影響する。**Step 3 より先に実行し、結果を `analysis.json.submodules_detected[]` に永続化する**。

```bash
git submodule status
```

各 submodule について:
- SSH URL (`git@github.com:`) は HTTPS に変換
- `setup.py` / `pyproject.toml` の有無を確認（Python パッケージかどうか）
- C++/CUDA 拡張の有無を確認:
  - `setup.py` に `ext_modules` / `CUDAExtension` / `CppExtension` があるか
  - `CMakeLists.txt` が存在するか
  - `.cu` / `.cuh` ファイルが存在するか

`analysis.json.submodules[]` に `{name, path, url, has_setup_py, has_cuda_extension}` を書き出す。Phase 2 の pixi-env-builder はこれを見て `[pypi-dependencies] name = { path, editable = true }` + `[pypi-options] no-build-isolation` を事前に pixi.toml へ書き込む。

### Step 6: デモコマンド特定

以下の順序で推論/デモコマンドを探す:

1. README.md の "Demo" / "Inference" / "Quick Start" / "Usage" セクション
2. `demo.py`, `run.py`, `inference.py`, `test.py`, `eval.py` の存在
3. `scripts/` ディレクトリ内のスクリプト
4. Makefile の推論関連ターゲット

### Step 7: モデルダウンロード方法の特定

README.md や スクリプトから以下を検出:
- `wget` / `curl` による直接ダウンロード
- `gdown` (Google Drive)
- `huggingface_hub` / `from_pretrained`
- カスタムダウンロードスクリプト

### Step 8: 難易度評価

以下の基準でリポジトリの再現難易度を評価し、`difficulty` フィールドに記録:

| 難易度 | 条件 |
|--------|------|
| easy | Type A1/B1/C1 + submodule なし + CUDA 不要 or 明確な CUDA バージョン指定 |
| medium | Type A2/A3/B2/B3 + submodule あり or CUDA 拡張ビルドが必要 |
| hard | Type D/E/F, 複数の submodule + C++/CUDA 拡張, 依存情報が不完全 |

### Step 8.5: CUDA↔PyTorch 互換チェック

Step 4 で特定した cuda_version と torch version を `cuda-dependency-resolver` の互換マトリクスと照合し、矛盾があれば `analysis.json.cuda_torch_compat_mismatch` に true + 推奨値を書き出す。Phase 2 がこれを見て attempt 1 を正しい組合せから始める。

### Step 9: reports/analysis.json 出力

全解析結果を `reports/analysis.json` として書き出す。スキーマは `/reimplement` コマンドの定義を参照。
