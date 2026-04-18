---
name: pixi-env-builder
description: reports/analysis.json の dep_type に基づいて pixi.toml を生成する。denkiwakame ワークフロー (Day 17/19) に準拠。/reimplement の Phase 2 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Write Edit Glob Grep
---

# pixi-env-builder: Pixi 環境構築パターン

`reports/analysis.json` の `dep_type` に基づき、適切な変換戦略で pixi.toml を生成する。

## Type A: conda 系 (environment.yml)

### A1: 完璧な environment.yml

```bash
pixi init --import environment.yml
```

生成された pixi.toml に対して共通処理を適用。

### A2: 不完全な environment.yml + submodule

1. environment.yml をコピーして cleaned 版を作成:
   - `pip:` セクションから submodule 関連の行を除去（`-e .`, `git+https://` 等）
   - `defaults` チャンネルを除去
2. `pixi init --import environment_cleaned.yml`
3. ベースだけで `pixi install` を通す（Divide-and-Conquer の第1段階）
4. submodule を1つずつ `[pypi-dependencies]` に追加:
   ```toml
   [pypi-dependencies]
   submodule-name = { path = "submodules/name", editable = true }
   ```
5. C++/CUDA 拡張を持つ submodule は no-build-isolation に追加:
   ```toml
   [pypi-options]
   no-build-isolation = ["submodule-name"]
   ```
6. 1つ追加するたびに `pixi install` で確認

### A3: environment.yml + requirements.txt 併用

A2 と同じフロー + requirements.txt の差分パッケージを pypi-dependencies に追加。

## Type B: pip 系 (requirements.txt)

**dep-converter スキルの requirements.txt パースルールを参照して変換。**

CV 論文で最も頻出するパターン。channels は `conda-forge` 単独が最もクリーン。

### B1: requirements.txt のみ

```bash
pixi init
```

生成された pixi.toml に対して:

1. `channels = ["conda-forge"]` を設定
2. `python` バージョンを追加（README / Dockerfile / ソースから推定）
3. requirements.txt を dep-converter のルールで `[pypi-dependencies]` に変換
4. PyTorch が含まれる場合:
   - `+cuXXX` サフィックスから CUDA バージョンを特定
   - `[pypi-options]` に `extra-index-urls` を追加
   - `[dependencies]` に `cuda-toolkit` を追加（CUDA 拡張ビルドが必要な場合）
5. `[system-requirements]` に `cuda` を設定

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

**Python バージョン選択の注意:**
- 最新の Python (3.12+) では一部パッケージの wheel が未提供の場合がある（例: open3d）
- wheel 互換性の問題が出たら Python を1つ下げる（3.12 → 3.11）

### B2: requirements.txt + setup.py

B1 と同じ + プロジェクト自体を editable install:

```toml
[pypi-dependencies]
project-name = { path = ".", editable = true }
```

### B3: 複数の requirements_*.txt

`_dev` / `_test` を含むファイルは除外し、残りを統合して B1 のフローへ。

## Type C: pyproject.toml 系 (modern Python)

**dep-converter スキルの pyproject.toml 変換ルールを参照。**

### C1: setuptools / hatch / flit (PEP 621 準拠)

```bash
pixi init --pyproject
```

既存の pyproject.toml に `[tool.pixi]` セクションが追加される。追加で設定:

```toml
[tool.pixi.workspace]
channels = ["conda-forge"]
platforms = ["linux-64"]

[tool.pixi.dependencies]
python = "3.11.*"
# CUDA が必要なら:
cuda-toolkit = "12.4.*"

[tool.pixi.system-requirements]
cuda = "12.4"

[tool.pixi.pypi-dependencies]
project-name = { path = ".", editable = true }
```

### C2: Poetry

1. `[tool.poetry.dependencies]` のバージョン記法を PEP 440 に変換（dep-converter 参照）
2. `[tool.poetry.group.dev.dependencies]` は除外
3. 変換後の依存で `[tool.pixi.pypi-dependencies]` を構築
4. `pixi init --pyproject` で統合

### C3: PDM

PDM は PEP 621 準拠なので C1 と同じフローで処理。

## Type E: setup.py / setup.cfg (legacy)

**dep-converter スキルの setup.py 抽出ルールを参照。**

### E1: setup.py のみ

1. AST パースで `install_requires` を抽出
2. 抽出した依存を Type B の変換フローに渡す
3. プロジェクト自体を editable install:
   ```toml
   [pypi-dependencies]
   project-name = { path = ".", editable = true }
   ```

### E2: setup.cfg のみ

`[options]` の `install_requires` を読み、E1 と同じフローで処理。

### E3: setup.py + requirements.txt 併存

requirements.txt を優先し Type B として処理。setup.py は editable install にのみ使用。

## Type D: Dockerfile 系

**dep-converter スキルの Dockerfile パースルールを参照。**

Dockerfile しか依存情報がないケース。命令を解析して Type A または Type B のフローに合流する。

### D1: Dockerfile with pip install

1. Dockerfile をパースし、`pip install` コマンドからパッケージリストを抽出
2. `pip install -r requirements.txt` があればそのファイルも読む
3. `FROM` のベースイメージから CUDA バージョンを推定
4. `apt-get install` からシステム依存を抽出 → dep-converter の apt→conda-forge マッピングで変換
5. 抽出した pip 依存を Type B のフローに合流:

```bash
pixi init
```

```toml
[workspace]
channels = ["conda-forge"]
platforms = ["linux-64"]

[dependencies]
python = "3.11.*"
# apt-get install から変換した conda-forge パッケージ:
mesalib = "*"
glib = "*"
ffmpeg = "*"

[pypi-dependencies]
# pip install から抽出:
torch = "==2.1.0"
torchvision = "==0.16.0"

[pypi-options]
extra-index-urls = ["https://download.pytorch.org/whl/cu121"]
```

### D2: Dockerfile with conda install

1. `conda install` コマンドからチャンネルとパッケージを抽出
2. `conda env create -f environment.yml` があればそのファイルも読む
3. 抽出結果を Type A のフローに合流（`pixi init --import` or 手動構築）

### D3: Dockerfile with apt + pip 混在

D1 と同じだが、apt 依存がより多い。apt→conda-forge マッピングで変換し、pip 依存は `[pypi-dependencies]` に:

1. apt パッケージを dep-converter のマッピングで conda-forge パッケージに変換
2. 対応がないマイナーな apt パッケージはスキップ（ビルドエラーで後から判明したら追加）
3. pip 依存を Type B の変換フローに渡す
4. `ENV` 命令の環境変数は pixi の `[activation]` に変換:
   ```toml
   [activation]
   scripts = ["env_vars.sh"]
   ```
   `env_vars.sh` に `export CUDA_HOME=...` 等を出力。

### Dockerfile パース時の注意

- **マルチステージビルド**: 最終ステージの依存のみを対象とする。`FROM ... AS builder` のステージはビルドツールのみ
- **ARG のデフォルト値**: `ARG CUDA_VERSION=12.1` はデフォルト値を使用
- **COPY --from**: バイナリコピーの場合はビルドステージの deps も必要になることがある
- **パッケージバージョンの欠落**: Dockerfile は `pip install numpy` のようにバージョン指定なしが多い → `"*"` で追加し、エラーが出たらバージョンを絞る

## Type F: 依存ファイルなし (source mining)

dep-converter スキルの「import 名 → PyPI パッケージ名マッピング」と「ファイル単位の除外」に従って依存リストを抽出し、その後 Type B のフローで pixi.toml を構築する。version は `"*"` か `">=X.0"` で開始し、`pixi install` / 推論時の ImportError から Experiment Loop で絞り込む。C ライブラリの暗黙依存はビルドエラーから発見して `pixi add` する。

---

## 共通処理 (全 Type に適用)

### 1. チャンネル設定

- `defaults` は必ず除去（miniconda 由来の environment.yml で混入しがち）
- conda pytorch を使う場合は**必ず** `channels = ["pytorch", "nvidia", "conda-forge"]` の順。詳細は `cuda-dependency-resolver` の「チャンネル順の絶対ルール」を参照 (逆順だと CPU-only torch が入って silent fail する)

### 2. CUDA 統一

`analysis.json.pixi_strategy.torch_source` に従う:
- `pypi_wheel` → torch は `[pypi-dependencies]`、nvcc が要るなら `cuda-toolkit` を conda-forge から
- `conda_pytorch` → pytorch チャンネル使用、`gcc`/`gxx` を明示追加

バージョン選択は `cuda-dependency-resolver` の互換マトリクスに従う。

### 3. Divide-and-Conquer (submodule がある場合)

```
Step 1: submodule 依存をすべて除外した状態で pixi install
Step 2: 成功したら submodule を1つずつ [pypi-dependencies] に追加:
        submodule-name = { path = "submodules/name", editable = true }
Step 3: 各追加後に pixi install で確認
Step 4: 失敗なら [pypi-options] no-build-isolation に追加
Step 5: それでも失敗なら git+https://...@{commit_hash} で固定
```

**`-e` と no-build-isolation の関係**:
pixi では `editable = true` が editable install を表す。`pip install -e submodule/` のような命令を後付けで走らせる必要はない。両方やると setuptools の develop mode が no-build-isolation と競合して build が落ちる。**pixi.toml に書いたら pip コマンドは走らせない。**

### 4. 環境検証 (install 成功後)

```bash
pixi run python --version
pixi run python -c "import torch; assert torch.cuda.is_available(), 'CPU-only torch detected — check channel order'; print(f'torch={torch.__version__}, device={torch.cuda.get_device_name(0)}')"
pixi run python -c "import numpy; import cv2; print('OK')"
```

`torch.cuda.is_available() == False` は **install 成功に見えても失敗** として扱う (Tier 0 で channels 順を直して再試行)。
