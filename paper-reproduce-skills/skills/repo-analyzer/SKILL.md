---
name: repo-analyzer
description: リポジトリの依存管理方式を解析し、6-Type分類を行い reports/analysis.json を生成する。/reimplement の Phase 1 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Glob Grep Write
---

# repo-analyzer: リポジトリ解析 + 6-Type 判定

CWD のリポジトリを解析し、Pixi 環境構築に必要な情報を `reports/analysis.json` に書き出す。`reports/` は Phase 0 で作成済み。

## Step 1: 依存ファイル検出

```bash
ls environment.yml environment.yaml conda_env.yml conda.yaml 2>/dev/null
ls requirements*.txt 2>/dev/null
ls pyproject.toml setup.py setup.cfg 2>/dev/null
find . -maxdepth 3 -iname "Dockerfile*" 2>/dev/null
```

検索パスは `analysis.json.dockerfile_search_note` に記録。

## Step 2: defaults チャンネル検出

environment.yml / conda.yaml の `channels:` に `defaults` があれば `pixi_strategy` に記録（Phase 2 で除去）。

## Step 3: submodule 検出（Step 4 より先に実行）

```bash
git submodule status
```

各 submodule について `analysis.json.submodules[]` に記録:

- SSH URL (`git@github.com:`) は HTTPS に変換
- `has_setup_py`: `setup.py` / `pyproject.toml` の有無
- `has_cuda_extension`: `ext_modules` / `CUDAExtension` / `CppExtension` / `CMakeLists.txt` / `.cu` / `.cuh` のいずれか

Phase 2 はこれを見て `[pypi-dependencies] name = { path, editable = true }` と `no-build-isolation` を事前注入する。

## Step 4: 6-Type 判定

優先順位: A > C > B > E > D > F。最も情報量の多いファイルで決定。

| Type | 条件 |
|---|---|
| A1 | environment.yml のみ、submodule の pip deps 行なし |
| A2 | environment.yml に submodule pip deps 行あり、または submodule 存在 |
| A3 | environment.yml + requirements.txt 併存 |
| C1 | pyproject.toml + `[build-system]` = setuptools/hatch/flit |
| C2 | pyproject.toml + `[tool.poetry]` |
| C3 | pyproject.toml + `[tool.pdm]` |
| B1 | requirements.txt 単独 |
| B2 | requirements.txt + setup.py |
| B3 | 複数の `requirements_*.txt` |
| E1 | setup.py 単独 |
| E2 | setup.cfg 単独 |
| E3 | setup.py + requirements.txt（B にフォールバック） |
| D1 | Dockerfile + pip install |
| D2 | Dockerfile + conda install |
| D3 | Dockerfile + apt + pip 混在 |
| F | 依存ファイル皆無 |

## Step 5: CUDA / PyTorch バージョン特定

優先度順:

1. environment.yml / requirements.txt の torch 指定
2. Dockerfile の `FROM`（例: `nvidia/cuda:12.1.0-...`）
3. README.md
4. setup.py / pyproject.toml
5. ソース中のバージョンチェック

複数検出時は environment.yml > Dockerfile > README を優先。

## Step 6: デモコマンド特定

1. README.md の "Demo" / "Inference" / "Quick Start" / "Usage" 節
2. `demo.py` / `run.py` / `inference.py` / `test.py` / `eval.py`
3. `scripts/` 配下
4. Makefile の推論ターゲット

## Step 7: モデルダウンロード方法

`wget` / `curl` / `gdown` / `huggingface_hub` / カスタムスクリプトのいずれかを検出。

## Step 8: 難易度評価

| 難易度 | 条件 |
|---|---|
| easy | A1/B1/C1 + submodule なし + CUDA 不要 or 明示指定 |
| medium | A2/A3/B2/B3 + submodule or CUDA 拡張ビルド |
| hard | D/E/F、複数 submodule + C++/CUDA 拡張、依存情報不完全 |

## Step 9: CUDA↔PyTorch 互換チェック

Step 5 の cuda_version と torch version を `cuda-dependency-resolver` の互換マトリクスと照合。矛盾時は `analysis.json.cuda_torch_compat_mismatch = true` + 推奨値を記録。Phase 2 は attempt 1 を推奨値で開始する。

## Step 10: Feasibility 判定

README / 論文から最低要件を抽出し、ホスト実測値と突合。`analysis.json.feasibility` に記録。

抽出項目（README の "Requirements" / "Hardware" / "Setup" 節、論文の実験設定表）:

| キー | 例 | 抽出先 |
|---|---|---|
| `min_vram_gb` | 24 / 40 / 80 | "requires 24GB GPU", "A100 80GB" |
| `min_disk_gb` | 100 | datasets / weights サイズ合計 |
| `min_cuda` | "11.8" | "CUDA >= 11.8" |
| `needs_auth` | true | HuggingFace gated, Google Form |

ホスト実測:

```bash
nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1  # MiB
df -BG --output=avail . | tail -1
nvcc --version 2>/dev/null | grep -oP 'release \K[0-9.]+'
```

判定:

- `infeasible`: `host_vram < min_vram_gb` かつ CPU fallback 不可 / `host_disk < min_disk_gb` / `needs_auth` かつ対応 env var 未設定 / 必須 DL URL が HEAD で 4xx・5xx
- `degraded`: `host_vram < min_vram_gb` だが CPU fallback 可 / URL 到達性のみ警告
- `ok`: 上記いずれにも該当せず

`analysis.json.feasibility`:

```json
{
  "status": "ok|degraded|infeasible",
  "requirements": {"min_vram_gb": 24, "min_disk_gb": null, "min_cuda": "11.8", "needs_auth": false},
  "host": {"vram_gb": 12, "disk_gb": 200, "cuda": "12.1"},
  "blockers": ["vram_shortage: need 24, have 12"]
}
```

## Step 11: reports/analysis.json 出力

全解析結果を `reports/analysis.json` に書き出す。スキーマは `/reimplement` の定義に従う。
