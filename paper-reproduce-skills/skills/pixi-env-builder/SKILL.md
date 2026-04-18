---
name: pixi-env-builder
description: reports/analysis.json の dep_type に基づいて pixi.toml を生成する。denkiwakame ワークフロー (Day 17/19) に準拠。/reimplement の Phase 2 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Write Edit Glob Grep
---

# pixi-env-builder: Pixi 環境構築パターン

`analysis.json.dep_type` に基づき pixi.toml を生成する。変換ルールは `dep-converter`、CUDA 関連は `cuda-dependency-resolver` に委譲する。

## Type A: conda 系（environment.yml）

### A1: 完璧な environment.yml

```bash
pixi init --import environment.yml
```

生成後に共通処理を適用。

### A2: 不完全 environment.yml + submodule

1. `environment.yml` をコピーし `environment_cleaned.yml` を作成:
   - `pip:` から submodule 関連（`-e .`, `git+https://`）を除去
   - `defaults` チャンネル除去
2. `pixi init --import environment_cleaned.yml`
3. ベースだけで `pixi install` 通過（Divide-and-Conquer 第 1 段階）
4. submodule を 1 つずつ追加:
   ```toml
   [pypi-dependencies]
   submodule-name = { path = "submodules/name", editable = true }
   ```
5. C++/CUDA 拡張持ちは `no-build-isolation` に追加:
   ```toml
   [pypi-options]
   no-build-isolation = ["submodule-name"]
   ```
6. 追加ごとに `pixi install` で確認

### A3: environment.yml + requirements.txt

A2 + requirements.txt の差分を `[pypi-dependencies]` に追加。

## Type B: pip 系（requirements.txt）

CV 論文で最頻出。`conda-forge` 単独チャンネルが最もクリーン。変換は `dep-converter` 参照。

### B1: requirements.txt のみ

```bash
pixi init
```

1. `channels = ["conda-forge"]` 設定
2. Python バージョン追加（README / Dockerfile / ソースから推定）
3. `dep-converter` のルールで `[pypi-dependencies]` に変換
4. PyTorch を含む場合:
   - `+cuXXX` サフィックスから CUDA バージョン特定
   - `[pypi-options] extra-index-urls` に URL 追加
   - CUDA 拡張ビルドが必要なら `cuda-toolkit` を `[dependencies]`
5. `[system-requirements] cuda` 設定

```toml
[workspace]
channels = ["conda-forge"]
platforms = ["linux-64"]

[system-requirements]
cuda = "12.4"

[dependencies]
python = "3.11.*"
cuda-toolkit = "12.4.*"

[pypi-dependencies]
torch = "==2.6.0"
torchvision = "==0.21.0"
numpy = "*"
opencv-contrib-python = "*"

[pypi-options]
extra-index-urls = ["https://download.pytorch.org/whl/cu124"]
```

Python 3.12+ で wheel 未提供のパッケージ（open3d 等）があれば 3.11 に下げる。

### B2: requirements.txt + setup.py

B1 + editable install:

```toml
[pypi-dependencies]
project-name = { path = ".", editable = true }
```

### B3: 複数 requirements_*.txt

`_dev` / `_test` は除外、残りを統合して B1 へ。

## Type C: pyproject.toml

変換は `dep-converter` 参照。

### C1: setuptools / hatch / flit (PEP 621)

```bash
pixi init --pyproject
```

```toml
[tool.pixi.workspace]
channels = ["conda-forge"]
platforms = ["linux-64"]

[tool.pixi.dependencies]
python = "3.11.*"
cuda-toolkit = "12.4.*"

[tool.pixi.system-requirements]
cuda = "12.4"

[tool.pixi.pypi-dependencies]
project-name = { path = ".", editable = true }
```

### C2: Poetry

1. `[tool.poetry.dependencies]` を PEP 440 に変換（dep-converter）
2. `[tool.poetry.group.dev.dependencies]` 除外
3. `[tool.pixi.pypi-dependencies]` に転記
4. `pixi init --pyproject` で統合

### C3: PDM

PEP 621 準拠のため C1 と同一フロー。

## Type E: setup.py / setup.cfg

抽出は `dep-converter` 参照。

### E1: setup.py

1. AST パースで `install_requires` 抽出
2. Type B の変換フローへ
3. editable install:
   ```toml
   [pypi-dependencies]
   project-name = { path = ".", editable = true }
   ```

### E2: setup.cfg

`[options] install_requires` を読み E1 と同じ。

### E3: setup.py + requirements.txt

requirements.txt 優先で Type B 処理。setup.py は editable install のみ。

## Type D: Dockerfile

Dockerfile のみが依存情報のケース。`dep-converter` のパースルールで命令を解析し、Type A/B のフローに合流。

### D1: Dockerfile + pip install

1. `pip install` からパッケージ抽出
2. `-r requirements.txt` があれば読み込み
3. `FROM` から CUDA バージョン推定
4. `apt-get install` を apt→conda-forge マッピングで変換
5. Type B フローに合流:

```toml
[workspace]
channels = ["conda-forge"]
platforms = ["linux-64"]

[dependencies]
python = "3.11.*"
mesalib = "*"
glib = "*"
ffmpeg = "*"

[pypi-dependencies]
torch = "==2.1.0"
torchvision = "==0.16.0"

[pypi-options]
extra-index-urls = ["https://download.pytorch.org/whl/cu121"]
```

### D2: Dockerfile + conda install

`conda install` / `conda env create -f` を抽出し Type A に合流。

### D3: Dockerfile + apt + pip 混在

D1 + `ENV` 命令を `[activation]` に変換:

```toml
[activation]
scripts = ["env_vars.sh"]
```

`env_vars.sh` に `export CUDA_HOME=...` 等を記述。対応のないマイナー apt パッケージはスキップ（ビルドエラー時に追加）。

### Dockerfile パース注意

- マルチステージ: 最終ステージの依存のみ対象
- `ARG` デフォルト値を展開に使用
- `COPY --from`: ビルドステージ deps が必要な場合あり
- バージョン未指定 (`pip install numpy`) は `"*"` で追加、エラー時に絞る

## Type F: 依存ファイルなし（source mining）

`dep-converter` の「import 名 → PyPI マッピング」と「ファイル除外」ルールで依存抽出後、Type B フローで構築。version は `"*"` か `">=X.0"` で開始し、ImportError から Experiment Loop で絞る。C ライブラリ暗黙依存はビルドエラーから発見して `pixi add`。

## 共通処理（全 Type 適用）

### チャンネル設定

- `defaults` は必ず除去（miniconda 由来で混入しがち）
- conda pytorch 使用時の順序は `cuda-dependency-resolver` 参照（`["pytorch", "nvidia", "conda-forge"]` 固定）

### CUDA 統一

`analysis.json.pixi_strategy.torch_source` に従う:
- `pypi_wheel` → torch は `[pypi-dependencies]`、nvcc 必要なら `cuda-toolkit` を conda-forge から
- `conda_pytorch` → pytorch channel + `gcc`/`gxx` 明示

バージョンは `cuda-dependency-resolver` の互換マトリクス参照。

### Divide-and-Conquer（submodule あり）

```
1. submodule 除外で pixi install 通過
2. submodule を 1 つずつ追加:
   name = { path = "submodules/name", editable = true }
3. 追加ごとに pixi install
4. 失敗 → [pypi-options] no-build-isolation に追加
5. それでも失敗 → git+https://...@{commit_hash} で固定
```

pixi では `editable = true` が editable install を表す。**pip コマンドを後付けで走らせない**（setuptools develop と no-build-isolation が競合する）。

### 環境検証（install 成功後）

```bash
pixi run python --version
pixi run python -c "import torch; assert torch.cuda.is_available(), 'CPU-only torch detected — check channel order'; print(f'torch={torch.__version__}, device={torch.cuda.get_device_name(0)}')"
pixi run python -c "import numpy; import cv2; print('OK')"
```

`torch.cuda.is_available() == False` は **install 成功に見えても失敗**（Tier 0 で channels 順修正）。
