---
name: dep-converter
description: 依存ファイル (requirements.txt, pyproject.toml, setup.py) から pixi.toml への変換パターン集。/reimplement の Phase 2 で自動参照される。
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
| `torch==2.1.0+cu121` | `torch = { version = "==2.1.0", index = "pytorch-cu121" }` ※ `+cuXXX` を除去し index 指定 |
| `torchvision==0.16.0+cu121` | `torchvision = { version = "==0.16.0", index = "pytorch-cu121" }` |
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

### PyTorch wheel index の設定

`torch==X.X.X+cuXXX` 形式を検出したら、以下の変換を行う:

1. `+cuXXX` サフィックスからCUDAバージョンを抽出 (例: `cu121` → `12.1`)
2. `[pypi-options]` に index URL を追加:
   ```toml
   [pypi-options]
   extra-index-urls = ["https://download.pytorch.org/whl/cu121"]
   ```
3. torch のバージョンから `+cuXXX` を除去:
   ```toml
   [pypi-dependencies]
   torch = "==2.1.0"
   ```

**`+cuXXX` が無い場合（バージョンのみ指定）:**
- Dockerfile や README から CUDA バージョンを推定
- 推定できなければ analysis.json の `cuda_version` を使用
- `extra-index-urls` で該当 CUDA バージョンの wheel index を指定

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
| libopencv-dev | opencv |
