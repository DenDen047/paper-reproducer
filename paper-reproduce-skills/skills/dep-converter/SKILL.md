---
name: dep-converter
description: 依存ファイル (requirements.txt, pyproject.toml, setup.py, Dockerfile) から pixi.toml への変換パターン集。/reimplement の Phase 2 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Write Edit Glob Grep
---

# dep-converter: 依存ファイル変換パターン集

各依存管理方式から Pixi の `[pypi-dependencies]` / `[pypi-options]` への変換ルールを定義する。

## requirements.txt パース (Type B)

### 行ごとの変換ルール

| requirements.txt の記法 | pixi.toml への変換 |
|---|---|
| `numpy==1.24.0` | `numpy = "==1.24.0"` |
| `numpy>=1.20,<2` | `numpy = ">=1.20,<2"` |
| `torch==2.1.0+cu121` | `torch = "==2.1.0"` + `[pypi-options] extra-index-urls = ["https://download.pytorch.org/whl/cu121"]` (下記詳細) |
| `torchvision==0.16.0+cu121` | 同上 |
| `git+https://github.com/user/repo.git` | `repo = { git = "https://github.com/user/repo.git" }` |
| `git+https://github.com/user/repo.git@main` | `repo = { git = "https://github.com/user/repo.git", branch = "main" }` |
| `git+https://github.com/user/repo.git@abc1234` | `repo = { git = "https://github.com/user/repo.git", rev = "abc1234" }` |
| `-e ./subdir` | `subdir = { path = "./subdir", editable = true }` |
| `-e .` | `project-name = { path = ".", editable = true }` |
| `package[extra1,extra2]` | `package = { version = "*", extras = ["extra1", "extra2"] }` |

### ディレクティブの変換

| requirements.txt | pixi.toml |
|---|---|
| `--find-links https://download.pytorch.org/whl/cu121` | `[pypi-options]` の `find-links` に追加 |
| `--extra-index-url https://download.pytorch.org/whl/cu121` | `[pypi-options]` の `extra-index-urls` に追加 |
| `-r another_requirements.txt` | 再帰的に読み込んで統合 |
| `# comment` | 無視 |
| 空行 | 無視 |
| `package ; python_version >= "3.8"` | 環境マーカーを除去（Linux のみ対象のため） |

### PyTorch wheel index の設定 (唯一の正規パターン)

`torch==X.X.X+cuXXX` 形式を検出したら:

1. `+cuXXX` サフィックスからCUDAバージョンを抽出 (例: `cu121` → `12.1`)
2. `[pypi-options] extra-index-urls` に URL を追加
3. torch のバージョンから `+cuXXX` を除去

```toml
[pypi-options]
extra-index-urls = ["https://download.pytorch.org/whl/cu121"]

[pypi-dependencies]
torch = "==2.1.0"
```

**`+cuXXX` が無い場合**:
- Dockerfile や README から CUDA バージョンを推定
- 推定できなければ `reports/analysis.json` の `cuda_version` を使用
- `extra-index-urls` に該当 CUDA の wheel index を指定

**使わないパターン (禁止)**:
`torch = { version = "==X", index = "pytorch-cu121" }` のような名前付き `index=` 参照は使わない。名前を `[pypi-options]` で定義し忘れると pixi.toml が syntax error で死ぬ。`extra-index-urls` に統一する。

### 複数 requirements ファイルの統合 (Type B3)

```
requirements.txt       → 基本依存（すべて含める）
requirements_gpu.txt   → CUDA 関連依存（含める）
requirements_train.txt → 訓練用依存（含める）
requirements_dev.txt   → 開発用依存（除外）
requirements_test.txt  → テスト用依存（除外）
```

`_dev` / `_test` を含むファイルは除外し、残りを統合する。

---

## pyproject.toml 変換 (Type C)

### C1: setuptools / hatch / flit (PEP 621 準拠)

既存の pyproject.toml に `[tool.pixi]` セクションを追加する。

```bash
pixi init --pyproject
```

これにより `[tool.pixi.workspace]` が追加される。追加で以下を設定:

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

### C2: Poetry → PEP 621 変換

Poetry の `[tool.poetry.dependencies]` を標準 PEP 621 形式に変換する。

**バージョン記法の変換:**

| Poetry | PEP 440 | 説明 |
|---|---|---|
| `^1.5` | `>=1.5,<2` | caret: メジャーバージョン互換 |
| `^0.5` | `>=0.5,<0.6` | caret (0.x): マイナーバージョン互換 |
| `~1.5` | `>=1.5,<1.6` | tilde: マイナーバージョン互換 |
| `1.5.*` | `==1.5.*` | ワイルドカード |
| `>=1.5,<2.0` | `>=1.5,<2.0` | そのまま |

**変換手順:**

1. `[tool.poetry.dependencies]` から `python` 以外を抽出
2. バージョン記法を PEP 440 に変換
3. `[tool.poetry.group.dev.dependencies]` は除外
4. extras は `[tool.poetry.extras]` から抽出
5. git 依存は `{ git = "...", branch = "..." }` 形式に変換
6. 変換後の依存を `[tool.pixi.pypi-dependencies]` に追加

### C3: PDM

PDM は PEP 621 準拠なので、通常は変換不要。`[tool.pdm]` セクションは無視し、C1 と同じフローで処理する。

---

## setup.py / setup.cfg 依存抽出 (Type E)

### E1: setup.py から install_requires を抽出

```bash
# AST パースで安全に抽出（setup.py を実行しない）
pixi run python -c "
import ast, sys
tree = ast.parse(open('setup.py').read())
for node in ast.walk(tree):
    if isinstance(node, ast.keyword) and node.arg == 'install_requires':
        try:
            deps = ast.literal_eval(node.value)
            for dep in deps:
                print(dep)
        except:
            pass
"
```

**AST パースが失敗する場合（動的な install_requires）:**

```python
# こういうパターンは AST では抽出できない:
install_requires = read_requirements('requirements.txt')
```

→ この場合は requirements.txt が存在するはずなので Type B にフォールバック (E3)。

### E2: setup.cfg から install_requires を抽出

```ini
[options]
install_requires =
    numpy>=1.20
    torch>=2.0
```

→ `[options]` セクションの `install_requires` を読んで、1行1パッケージとしてパース。Type B の変換ルールで pixi.toml に変換。

### E3: setup.py + requirements.txt 併存

requirements.txt を優先し、Type B として処理する。setup.py は editable install に使用:

```toml
[pypi-dependencies]
project-name = { path = ".", editable = true }
```

---

## Dockerfile パース (Type D)

### 命令ごとの抽出ルール

Dockerfile を行ごとにパースし、依存情報を抽出する。

#### FROM: ベースイメージから CUDA バージョン推定

| FROM 命令 | 推定結果 |
|---|---|
| `FROM nvidia/cuda:12.1.0-devel-ubuntu22.04` | CUDA 12.1 |
| `FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu20.04` | CUDA 11.8 |
| `FROM pytorch/pytorch:2.1.0-cuda12.1-cudnn8-devel` | CUDA 12.1, PyTorch 2.1.0 |
| `FROM python:3.11-slim` | CUDA なし（後続命令で判断） |
| `FROM ubuntu:22.04` | CUDA なし |

**推定ロジック**: `nvidia/cuda:X.Y.Z` → X.Y を抽出。`pytorch/pytorch:A.B.C-cudaX.Y` → CUDA X.Y + PyTorch A.B.C。

#### RUN apt-get install: システム依存の抽出

```dockerfile
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    ffmpeg \
    git wget unzip
```

→ パッケージ名を1つずつ抽出し、apt→conda-forge マッピング（後述）で変換。

**パースの注意:**
- `\` による行継続を結合してからパース
- `&&` で連結されたコマンドを個別に処理
- `-y`, `--no-install-recommends` 等のフラグは無視
- `apt-get update` は無視

#### RUN pip install: Python 依存の抽出

| Dockerfile の pip コマンド | 抽出結果 |
|---|---|
| `pip install numpy torch==2.1.0` | `numpy`, `torch==2.1.0` → Type B 変換ルールへ |
| `pip install -r requirements.txt` | requirements.txt ファイルを読んで Type B パース |
| `pip install -e .` | `project = { path = ".", editable = true }` |
| `pip install git+https://github.com/user/repo.git` | git 依存として変換 |
| `pip install --no-cache-dir torch` | `--no-cache-dir` は無視し `torch` を抽出 |

**パースの注意:**
- `pip install` / `pip3 install` / `python -m pip install` をすべて捕捉
- `--no-cache-dir`, `--upgrade`, `-U` 等のフラグは無視
- `pip install package1 package2` の複数指定に対応

#### RUN conda install: conda 依存の抽出

| Dockerfile の conda コマンド | 抽出結果 |
|---|---|
| `conda install -c pytorch torch torchvision` | channel: pytorch, deps: torch, torchvision |
| `conda install -c conda-forge numpy` | channel: conda-forge, deps: numpy |
| `conda env create -f environment.yml` | environment.yml を読んで Type A パース |
| `conda install -y python=3.11` | deps: python=3.11 |

#### ENV: 環境変数の抽出

| Dockerfile の ENV | pixi.toml への変換 |
|---|---|
| `ENV CUDA_HOME=/usr/local/cuda` | `[activation]` scripts に `export CUDA_HOME=/usr/local/cuda` |
| `ENV TORCH_CUDA_ARCH_LIST="7.0 7.5 8.0 8.6"` | activation script に export |
| `ENV FORCE_CUDA=1` | activation script に export |
| `ENV PATH=/opt/conda/bin:$PATH` | 通常は不要（pixi が管理）→ スキップ |
| `ENV LD_LIBRARY_PATH=...` | 必要に応じて activation script に追加 |

**スキップする ENV:**
- `PATH` の変更（pixi が管理）
- `DEBIAN_FRONTEND=noninteractive`（apt 用）
- `PYTHONDONTWRITEBYTECODE`, `PYTHONUNBUFFERED`（実行時設定）

### マルチステージビルドの処理

```dockerfile
FROM nvidia/cuda:12.1.0-devel AS builder
RUN pip install cmake ninja
RUN pip install -e ./custom_ops

FROM nvidia/cuda:12.1.0-runtime
COPY --from=builder /opt/custom_ops /opt/custom_ops
RUN pip install torch numpy
```

**ルール:**
1. 全ステージの `FROM` を列挙し、最終ステージを特定
2. 最終ステージの pip/conda/apt 依存を主たる依存とする
3. `COPY --from=builder` でビルド済みバイナリがコピーされる場合:
   - builder ステージのビルド依存（cmake, ninja 等）も pixi に追加
   - ビルド対象のパッケージは `[pypi-dependencies]` に editable install で追加
4. 最終ステージが `runtime` イメージの場合、ビルドには `devel` 相当のツールが必要 → `cuda-toolkit` を追加

### ARG のデフォルト値

```dockerfile
ARG CUDA_VERSION=12.1
ARG PYTHON_VERSION=3.11
FROM nvidia/cuda:${CUDA_VERSION}.0-devel-ubuntu22.04
```

→ `ARG` のデフォルト値を使用して `FROM` を展開する。

---

## import 名 → PyPI パッケージ名マッピング (Type F 用)

よく遭遇する不一致のマッピングテーブル:

| import 名 | PyPI パッケージ名 |
|---|---|
| cv2 | opencv-python (or opencv-python-headless) |
| PIL | pillow |
| sklearn | scikit-learn |
| yaml | pyyaml |
| skimage | scikit-image |
| attr | attrs |
| bs4 | beautifulsoup4 |
| dotenv | python-dotenv |
| git | gitpython |
| serial | pyserial |
| usb | pyusb |
| wx | wxpython |
| Crypto | pycryptodome |

### Python 標準ライブラリ（除外リスト）

Type F の import スキャン時に除外すべき主要な標準ライブラリモジュール:

```
os, sys, re, math, json, csv, io, time, datetime, pathlib, typing,
collections, itertools, functools, operator, copy, pickle, shelve,
hashlib, hmac, secrets, struct, codecs, unicodedata, textwrap, difflib,
string, abc, contextlib, dataclasses, enum, numbers, decimal, fractions,
random, statistics, argparse, logging, warnings, traceback, unittest,
pdb, profile, timeit, glob, shutil, tempfile, subprocess, socket,
http, urllib, email, html, xml, sqlite3, zipfile, tarfile, gzip, bz2,
lzma, configparser, threading, multiprocessing, concurrent, asyncio,
signal, mmap, queue, ctypes, inspect, importlib, pkgutil, pprint,
bisect, heapq, array, weakref, types, dis, ast, token, tokenize,
compileall, site, sysconfig, platform, errno, faulthandler, gc
```

**判定ルール**: 上記に含まれる、または `_` で始まるモジュールは除外。それ以外はサードパーティと判定。

### ファイル単位の除外 (Type F 過剰抽出の防止)

import スキャン対象から除外するファイル:

- `tests/`, `test_*.py`, `*_test.py` — テスト専用 (pytest, hypothesis 等を誤検出)
- `benchmarks/`, `bench_*.py` — ベンチ専用
- `scripts/` 配下で **demo_commands に列挙されていない** スクリプト — 学習ユーティリティが多い
- `docs/`, `examples/notebooks/*.ipynb` — 実行時の依存ではない

README の demo_commands (analysis.json) に現れるエントリポイントから逆算した**必要最小の依存**を第一候補にする。不足は experiment-loop で後から追加できるので、初期は絞って出す。

---

## apt → conda-forge パッケージマッピング (Type D 用)

Dockerfile の `apt-get install` から pixi conda-forge パッケージへの変換:

| apt パッケージ | conda-forge パッケージ |
|---|---|
| libgl1-mesa-glx | mesalib |
| libglib2.0-0 | glib |
| libsm6 | xorg-libsm |
| libxext6 | xorg-libxext |
| libxrender1 | xorg-libxrender |
| ffmpeg | ffmpeg |
| build-essential | cxx-compiler |
| cmake | cmake |
| ninja-build | ninja |
| git | git |
| wget | wget |
| unzip | unzip |
| libopencv-dev | opencv |
