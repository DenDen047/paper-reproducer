---
name: pixi-env-builder
description: analysis.json の dep_type に基づいて pixi.toml を生成する。denkiwakame ワークフロー (Day 17/19) に準拠。/reimplement の Phase 2 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Write Edit Glob Grep
---

# pixi-env-builder: Pixi 環境構築パターン

analysis.json の `dep_type` に基づき、適切な変換戦略で pixi.toml を生成する。

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

## Type B: pip 系 (requirements.txt) — Phase 2 で実装予定

Phase 1 では Type A に集中。Type B は dep-converter スキルと合わせて Phase 2 で実装。

## Type C/D/E/F — Phase 2/3 で実装予定

---

## 共通処理: denkiwakame ルール（全 Type に適用）

### 1. defaults チャンネル除去

pixi.toml の `channels` から `"defaults"` を必ず除去する。miniconda 由来の environment.yml で混入しがち。

```toml
# BEFORE (NG)
channels = ["defaults", "conda-forge"]

# AFTER (OK)
channels = ["conda-forge"]
```

元リポジトリが conda pytorch を使っている場合は pytorch / nvidia チャンネルを許容:
```toml
channels = ["pytorch", "nvidia", "conda-forge"]
```

### 2. CUDA 統一

analysis.json の `pixi_strategy.torch_source` に基づく:

**PyPI wheel の場合** (torch_source = "pypi_wheel"):
- torch は `[pypi-dependencies]` に入れる
- nvcc が必要な submodule ビルドには `cuda-toolkit` を conda-forge から追加:
  ```toml
  [dependencies]
  cuda-toolkit = "12.1.*"
  ```

**conda pytorch の場合** (torch_source = "conda_pytorch"):
- pytorch / nvidia チャンネルを追加
- gcc/gxx を明示的に追加（nvidia channel では外から見えない）:
  ```toml
  [dependencies]
  pytorch = ">=2.1"
  gcc = ">=11"
  gxx = ">=11"
  ```

### 3. system-requirements.cuda

ホスト GPU ドライバの要件を申告する。これは pixi 環境内の CUDA バージョンとは別物。

```toml
[system-requirements]
cuda = "12.1"
```

### 4. gcc/gxx を pixi 管理下に

nvidia channel の CUDA では gcc/g++ が外側から見えない問題がある (Day 17)。
C++/CUDA 拡張をビルドする場合は必ず追加:

```toml
[dependencies]
gcc = ">=11"
gxx = ">=11"
cmake = ">=3.20"
```

conda-forge の CUDA を使う場合は `c-compiler` / `cxx-compiler` メタパッケージも利用可能:
```toml
[dependencies]
c-compiler = "*"
cxx-compiler = "*"
```

### 5. Divide-and-Conquer 実行パターン

```
Step 1: submodule 依存をすべて除外した状態で pixi install
Step 2: 成功したら submodule を1つずつ追加
Step 3: 各追加後に pixi install で確認
Step 4: 失敗した submodule は no-build-isolation を試す
Step 5: それでも失敗なら git+https://...@{commit_hash} で固定バージョンを試す
```

### 6. no-build-isolation

PEP 517 違反の C++/CUDA 拡張パッケージに必要。pixi 環境内の CUDA/gcc をビルドに使わせるため。

```toml
[pypi-options]
no-build-isolation = ["diff-gaussian-rasterization", "simple-knn"]
```

### 7. 環境検証

`pixi install` 成功後に以下を確認:

```bash
# Python バージョン
pixi run python --version

# PyTorch + CUDA
pixi run python -c "import torch; print(f'torch={torch.__version__}, cuda={torch.cuda.is_available()}, device={torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')"

# 主要モジュールの import テスト
pixi run python -c "import numpy; import cv2; print('OK')"
```
