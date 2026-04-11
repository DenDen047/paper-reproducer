---
name: cuda-dependency-resolver
description: CUDA依存の統一的解決。4つのCUDA問題、nvidia vs conda-forge チャンネル選択、system-requirements.cuda、gcc/gxx 管理。/reimplement の Phase 2 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Write Edit Grep
---

# cuda-dependency-resolver: CUDA 依存解決

CV 論文リポジトリで最も厄介な CUDA 依存を統一的に解決するスキル。
denkiwakame 氏の Day 17 (pixi で CUDA を管理する) に準拠。

## 4つの CUDA 問題

野良リポジトリでは以下の4箇所から CUDA が混入し、バージョン不整合を起こす:

1. **PyPI wheel に同梱された CUDA runtime** (torch の wheel 等)
2. **conda パッケージの CUDA** (conda-forge or nvidia channel)
3. **Docker base image の CUDA** (FROM nvidia/cuda:...)
4. **ホストにインストーラで入れた CUDA** (/usr/local/cuda)

**解決方針**: Pixi で1つに統一する。

## CUDA バージョン決定フロー

```
1. `reports/analysis.json` の cuda_version を確認
2. 未特定の場合:
   - PyTorch バージョンから推定:
     torch 2.0-2.1 → CUDA 11.8 or 12.1
     torch 2.2+    → CUDA 12.1 or 12.4
   - README / Dockerfile から推定
3. デフォルト: CUDA 12.1 (最も互換性が高い)
```

## nvidia channel vs conda-forge channel

| 観点 | nvidia | conda-forge |
|------|--------|-------------|
| gcc/g++ | 外から見えない (要 pixi add) | c/cxx-compiler で共有可能 |
| CUDA 12+ | OK | 推奨 |
| CUDA 11 以下 | 推奨 | 非推奨 |
| バージョン指定 | channel label で絞る | cuda-version メタパッケージ |

### 判定ロジック

```
if cuda_version >= 12:
    cuda_channel = "conda-forge"  # 推奨
    # cuda-version メタパッケージでバージョン指定
    # c-compiler / cxx-compiler が使える
elif cuda_version < 12:
    cuda_channel = "nvidia"
    # channel label で絞る (例: nvidia/label/cuda-11.8.0)
    # gcc/gxx を明示的に pixi add する必要あり
```

## pixi.toml への適用パターン

### パターン 1: conda-forge CUDA + PyPI torch (推奨)

最もクリーンな構成。CUDA 12+ 向け。

```toml
[project]
channels = ["conda-forge"]
platforms = ["linux-64"]

[dependencies]
python = ">=3.10"
cuda-toolkit = "12.1.*"
cuda-version = "12.1"
c-compiler = "*"
cxx-compiler = "*"
cmake = ">=3.20"

[pypi-dependencies]
torch = ">=2.1"
torchvision = ">=0.16"

[system-requirements]
cuda = "12.1"
```

### パターン 2: nvidia channel CUDA 12+ + conda torch

元リポジトリが conda pytorch を使っていて CUDA 12+ の場合。

```toml
[project]
channels = ["pytorch", "nvidia", "conda-forge"]
platforms = ["linux-64"]

[dependencies]
python = ">=3.10"
pytorch = ">=2.1"
torchvision = ">=0.16"
cuda = "12.1.*"
gcc = "11.*"
gxx = "11.*"
cmake = ">=3.20"

[system-requirements]
cuda = "12.1"
```

### パターン 3: nvidia channel CUDA 11.x (レガシー)

古い論文で CUDA 11.x を要求する場合。**channel label でバージョンを絞ることが必須。**

**CRITICAL**: CUDA 11.x では `cuda-toolkit` メタパッケージを使ってはいけない。nvidia channel の `cuda-toolkit` は最新版 (12.x) に解決されてしまう。代わりに:
1. `nvidia/label/cuda-{version}` channel label を追加してバージョンを絞る
2. `cuda = "{version}.*"` メタパッケージでピン留めする
3. `gcc`/`gxx` は CUDA バージョンに合わせて上限を設定する (CUDA 11.x → gcc <12)

```toml
[project]
channels = ["pytorch", "nvidia/label/cuda-11.7.0", "nvidia", "conda-forge"]
platforms = ["linux-64"]

[dependencies]
python = ">=3.8,<3.11"
pytorch = "2.0.1.*"
pytorch-cuda = "11.7.*"
torchvision = "0.15.2.*"
cuda = "11.7.*"
gcc = "11.*"
gxx = "11.*"

[system-requirements]
cuda = "11.7"
```

**よくあるミス（してはいけない）:**
- `cuda-toolkit = "11.7.*"` → nvidia channel では 12.x に解決されることがある。`cuda = "11.7.*"` を使う
- `channels = ["pytorch", "nvidia", "conda-forge"]` で CUDA 11.x → label なしの nvidia channel は最新版を引く。`nvidia/label/cuda-11.7.0` を追加する
- `gcc = ">=11,<13"` で CUDA 11.x → g++ 12.x が入り CUDA 11.x と非互換。`gcc = "11.*"` にピンする

## system-requirements.cuda

**重要**: これはホスト GPU ドライバの要件申告であり、pixi 環境内の CUDA バージョンとは別物。

- ホストの nvidia-smi で表示される CUDA バージョン以下を指定する
- pixi はこの値を見て、互換性のあるパッケージを解決する
- 実際の CUDA toolkit は `[dependencies]` の `cuda-toolkit` で指定する

```toml
# ホストドライバが CUDA 12.4 対応の場合、12.1 を要求しても OK
[system-requirements]
cuda = "12.1"
```

## gcc/gxx の管理

### nvidia channel 使用時 (必須)

nvidia channel の CUDA パッケージでは gcc/g++ が環境外から見えない (Day 17)。
C++/CUDA 拡張をビルドする submodule がある場合は必ず追加:

```toml
[dependencies]
gcc = ">=11"
gxx = ">=11"
```

### conda-forge 使用時 (推奨)

conda-forge の `c-compiler` / `cxx-compiler` メタパッケージが利用可能:

```toml
[dependencies]
c-compiler = "*"
cxx-compiler = "*"
```

## CUDA 関連エラーの診断

| エラー | 原因 | 対処 |
|--------|------|------|
| `nvcc not found` | cuda-toolkit 未追加 | `pixi add cuda-toolkit` (12+) or `pixi add cuda` (11.x) |
| `gcc: command not found` (ビルド時) | gcc が pixi 環境にない | `pixi add gcc gxx` |
| nvcc バージョンが想定と違う (例: 12.4 vs 11.7) | `cuda-toolkit` メタパッケージが最新版に解決された | `nvidia/label/cuda-{version}` channel + `cuda = "{version}.*"` に変更 |
| `error: -- unsupported GNU version! gcc versions later than X are not supported!` | gcc が CUDA バージョンの上限を超えている | CUDA 11.x → `gcc = "11.*"`, CUDA 12.x → `gcc = "12.*"` |
| `CUDA_HOME is not set` | 環境変数未設定 | pixi activation script で設定、または `pixi add cuda-toolkit` で自動設定 |
| `RuntimeError: CUDA error: no kernel image` | CUDA compute capability 不一致 | torch の CUDA バージョンと GPU アーキテクチャを確認 |
| `libcudart.so: cannot open shared object` | CUDA runtime 不一致 | PyPI wheel と conda CUDA が競合 → 片方に統一 |
| `error: unsupported gpu architecture 'compute_90'` | 古い CUDA で新 GPU | CUDA バージョンを上げる |
| `undefined symbol: __cudaRegisterLinkedBinary` | ドライバ不整合 | system-requirements.cuda をホストドライバに合わせる |

## 環境変数の設定

CUDA 拡張のビルドに必要な環境変数を pixi の activation script で設定:

```toml
[activation]
scripts = ["setup_env.sh"]
```

`setup_env.sh`:
```bash
export CUDA_HOME=$CONDA_PREFIX
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
```
