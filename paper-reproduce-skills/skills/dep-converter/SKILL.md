---
name: dep-converter
description: 依存ファイル (requirements.txt, pyproject.toml, setup.py, Dockerfile) から pixi.toml への変換パターン集。/reimplement の Phase 2 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Write Edit Glob Grep
---

# dep-converter: 依存ファイル変換パターン集

各依存管理方式から Pixi の `[pypi-dependencies]` / `[pypi-options]` への変換ルール。

## requirements.txt パース（Type B）

### 行変換

| requirements.txt | pixi.toml |
|---|---|
| `numpy==1.24.0` | `numpy = "==1.24.0"` |
| `numpy>=1.20,<2` | `numpy = ">=1.20,<2"` |
| `torch==2.1.0+cu121` | `torch = "==2.1.0"` + `extra-index-urls` に該当 URL |
| `git+https://.../repo.git` | `repo = { git = "https://.../repo.git" }` |
| `git+https://.../repo.git@main` | `repo = { git = "...", branch = "main" }` |
| `git+https://.../repo.git@abc1234` | `repo = { git = "...", rev = "abc1234" }` |
| `-e ./subdir` | `subdir = { path = "./subdir", editable = true }` |
| `-e .` | `project-name = { path = ".", editable = true }` |
| `package[extra1,extra2]` | `package = { version = "*", extras = ["extra1", "extra2"] }` |

### ディレクティブ

| requirements.txt | pixi.toml |
|---|---|
| `--find-links URL` | `[pypi-options] find-links` に追加 |
| `--extra-index-url URL` | `[pypi-options] extra-index-urls` に追加 |
| `-r another.txt` | 再帰読み込みで統合 |
| `# comment` / 空行 | 無視 |
| `package ; python_version >= "3.8"` | 環境マーカーを除去（Linux 限定） |

### PyTorch wheel index（正規パターン）

`torch==X.X.X+cuXXX` を検出したら:

1. `+cuXXX` から CUDA バージョン抽出（`cu121` → `12.1`）
2. URL を `[pypi-options] extra-index-urls` に追加
3. torch バージョンから `+cuXXX` を除去

```toml
[pypi-options]
extra-index-urls = ["https://download.pytorch.org/whl/cu121"]

[pypi-dependencies]
torch = "==2.1.0"
```

`+cuXXX` なしの場合は Dockerfile / README / `analysis.json.cuda_version` の順で推定。

### MUST NOT

- `torch = { version = "==X", index = "pytorch-cu121" }` の名前付き `index=` 参照は禁止（`[pypi-options]` で定義し忘れると syntax error で死ぬ）。`extra-index-urls` に統一する。

### 複数 requirements 統合（Type B3）

| ファイル | 扱い |
|---|---|
| `requirements.txt` | 含める |
| `requirements_gpu.txt` | 含める |
| `requirements_train.txt` | 含める |
| `requirements_dev.txt` | 除外 |
| `requirements_test.txt` | 除外 |

`_dev` / `_test` を含むファイルを除外し、残りを統合。

## pyproject.toml 変換（Type C）

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

### C2: Poetry → PEP 621

| Poetry | PEP 440 |
|---|---|
| `^1.5` | `>=1.5,<2` |
| `^0.5` | `>=0.5,<0.6` |
| `~1.5` | `>=1.5,<1.6` |
| `1.5.*` | `==1.5.*` |
| `>=1.5,<2.0` | そのまま |

手順:
1. `[tool.poetry.dependencies]` から `python` 以外を抽出
2. PEP 440 に変換
3. `[tool.poetry.group.dev.dependencies]` 除外
4. extras は `[tool.poetry.extras]` から
5. git 依存は `{ git = "...", branch = "..." }` 形式
6. `[tool.pixi.pypi-dependencies]` に転記

### C3: PDM

PEP 621 準拠。C1 と同じフローで処理（`[tool.pdm]` は無視）。

## setup.py / setup.cfg 抽出（Type E）

### E1: setup.py

```bash
pixi run python -c "
import ast
tree = ast.parse(open('setup.py').read())
for node in ast.walk(tree):
    if isinstance(node, ast.keyword) and node.arg == 'install_requires':
        try:
            for dep in ast.literal_eval(node.value):
                print(dep)
        except:
            pass
"
```

動的な `install_requires`（`read_requirements('requirements.txt')` 等）は AST で抽出不能 → requirements.txt が存在するので Type B フォールバック (E3)。

### E2: setup.cfg

```ini
[options]
install_requires =
    numpy>=1.20
    torch>=2.0
```

`[options] install_requires` を 1 行 1 パッケージで読み、Type B へ。

### E3: setup.py + requirements.txt

requirements.txt 優先で Type B 処理。setup.py は editable install のみ:

```toml
[pypi-dependencies]
project-name = { path = ".", editable = true }
```

## Dockerfile パース（Type D）

### FROM: CUDA バージョン推定

| FROM | 推定 |
|---|---|
| `nvidia/cuda:12.1.0-devel-ubuntu22.04` | CUDA 12.1 |
| `nvidia/cuda:11.8.0-cudnn8-devel-ubuntu20.04` | CUDA 11.8 |
| `pytorch/pytorch:2.1.0-cuda12.1-cudnn8-devel` | CUDA 12.1, PyTorch 2.1.0 |
| `python:3.11-slim` / `ubuntu:22.04` | CUDA なし |

`nvidia/cuda:X.Y.Z` → X.Y を抽出。`pytorch/pytorch:A.B.C-cudaX.Y` → CUDA X.Y + PyTorch A.B.C。

### RUN apt-get install

行継続 `\` を結合 → `&&` で分割 → パッケージ名抽出 → apt→conda-forge マッピング（後述）で変換。`-y` / `--no-install-recommends` / `apt-get update` は無視。

### RUN pip install

| コマンド | 抽出 |
|---|---|
| `pip install numpy torch==2.1.0` | `numpy`, `torch==2.1.0` → Type B |
| `pip install -r requirements.txt` | ファイル読み込み |
| `pip install -e .` | `project = { path = ".", editable = true }` |
| `pip install git+https://.../repo.git` | git 依存 |
| `pip install --no-cache-dir torch` | フラグを無視して `torch` |

`pip install` / `pip3 install` / `python -m pip install` を全て捕捉。`--no-cache-dir` / `--upgrade` / `-U` は無視。

### RUN conda install

| コマンド | 抽出 |
|---|---|
| `conda install -c pytorch torch torchvision` | channel: pytorch, deps |
| `conda install -c conda-forge numpy` | channel: conda-forge, deps |
| `conda env create -f environment.yml` | environment.yml 読み込み → Type A |
| `conda install -y python=3.11` | deps: python=3.11 |

### ENV

| ENV | 変換 |
|---|---|
| `CUDA_HOME=/usr/local/cuda` | activation に `export CUDA_HOME=...` |
| `TORCH_CUDA_ARCH_LIST="..."` | activation に export |
| `FORCE_CUDA=1` | activation に export |
| `LD_LIBRARY_PATH=...` | 必要に応じて activation |

スキップ: `PATH`（pixi 管理）、`DEBIAN_FRONTEND=noninteractive`、`PYTHONDONTWRITEBYTECODE`、`PYTHONUNBUFFERED`。

### マルチステージ

1. 最終ステージを特定
2. 最終ステージの pip/conda/apt 依存を主依存とする
3. `COPY --from=builder` がある場合:
   - builder のビルド依存（cmake, ninja 等）も追加
   - ビルド対象は editable install で追加
4. 最終が `runtime` イメージなら `cuda-toolkit` を追加（`devel` 相当のツールが必要）

### ARG デフォルト値

`ARG CUDA_VERSION=12.1` はデフォルト値で `FROM` を展開。

## import 名 → PyPI マッピング（Type F）

| import 名 | PyPI |
|---|---|
| cv2 | opencv-python / opencv-python-headless |
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

### 標準ライブラリ除外リスト

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

上記か `_` で始まるモジュールは除外。それ以外はサードパーティ。

### ファイル除外（Type F 過剰抽出防止）

- `tests/` / `test_*.py` / `*_test.py` — pytest, hypothesis 等の誤検出
- `benchmarks/` / `bench_*.py` — ベンチ専用
- `scripts/` 配下で **demo_commands 未列挙** のスクリプト — 学習ユーティリティ
- `docs/` / `examples/notebooks/*.ipynb` — 実行時依存ではない

`analysis.json.demo_commands` のエントリポイントから逆算した必要最小依存を第一候補とする。不足は experiment-loop で追加するため初期は絞る。

## apt → conda-forge マッピング（Type D）

| apt | conda-forge |
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
