---
name: cuda-dependency-resolver
description: CUDA依存の統一的解決。4つのCUDA問題、nvidia vs conda-forge チャンネル選択、system-requirements.cuda、gcc/gxx 管理。/reimplement の Phase 2 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Write Edit Grep
---

# cuda-dependency-resolver: CUDA 依存解決

denkiwakame Day 17 準拠。野良リポジトリの CUDA 依存を Pixi で1つに統一する。

## 4つの CUDA 混入源

1. PyPI wheel 同梱 (torch 等)
2. conda パッケージ (conda-forge / nvidia)
3. Docker base image (`FROM nvidia/cuda:...`)
4. ホストインストーラ (`/usr/local/cuda`)

## CUDA ↔ PyTorch 互換マトリクス

| torch | 推奨 CUDA | 備考 |
|---|---|---|
| < 2.2 | 11.8 | 2.0.x は 12.x 不可。`nvidia/label/cuda-11.8.0` を使う |
| 2.2 – 2.4 | 12.1 / 12.4 | 両方可、conda-forge が無難 |
| ≥ 2.5 | 12.4 / 12.6 | Ada/Hopper は 12.4+ 必須 |

未特定時:
- torch のみ判明 → 上表で CUDA を決定
- 両方不明 → CUDA 12.1（最も互換性高い）

torch 2.0.x + CUDA 12.x はビルドで死ぬ。Phase 0 pre-flight で Tier 0 として先に直す。

## チャンネル選択

| 条件 | channel |
|---|---|
| CUDA ≥ 12 | conda-forge |
| CUDA < 12 | nvidia（label で絞る） |

## チャンネル順の絶対ルール（conda pytorch 使用時）

pixi resolver は先頭優先で探索。先頭で torch が見つかれば打ち切るため、順序を間違えると **CPU-only torch が先勝ち**して CUDA 不在のまま「install 成功」扱いになる。

```toml
# ✅ 正しい
channels = ["pytorch", "nvidia", "conda-forge"]

# ❌ 逆順は CPU-only torch が勝つ
channels = ["conda-forge", "pytorch", "nvidia"]
```

PyPI torch wheel（dep-converter の `extra-index-urls` パターン）使用時は適用外。

## 適用パターン

### パターン 1: conda-forge CUDA + PyPI torch（推奨、CUDA 12+）

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

### パターン 2: nvidia channel + conda torch（CUDA 12+）

```toml
[project]
channels = ["pytorch", "nvidia", "conda-forge"]

[dependencies]
python = ">=3.10"
pytorch = ">=2.1"
torchvision = ">=0.16"
cuda = "12.1.*"
gcc = "11.*"
gxx = "11.*"

[system-requirements]
cuda = "12.1"
```

### パターン 3: CUDA 11.x レガシー

CUDA 11.x では **`cuda-toolkit` メタパッケージ禁止**（nvidia channel で 12.x に解決される）。

必須:
- `nvidia/label/cuda-{version}` channel label でバージョン固定
- `cuda = "{version}.*"` で pin
- gcc は CUDA に合わせて上限設定（CUDA 11.x → `gcc = "11.*"`）

```toml
[project]
channels = ["pytorch", "nvidia/label/cuda-11.7.0", "nvidia", "conda-forge"]

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

**MUST NOT（CUDA 11.x）:**
- `cuda-toolkit = "11.7.*"` を使う（12.x に解決される）
- label なし `nvidia` channel で固定する（最新版を引く）
- `gcc = ">=11,<13"` で指定する（g++ 12.x が入り非互換）

## system-requirements.cuda

ホスト GPU ドライバ要件の申告であり、環境内 CUDA とは別物。`nvidia-smi` 表示バージョン以下を指定する。pixi はこの値で互換解決する。実際の toolkit は `[dependencies] cuda-toolkit` で指定。

## gcc/gxx 管理

| channel | 追加方法 |
|---|---|
| nvidia | 必須: `gcc = ">=11"` + `gxx = ">=11"`（nvidia の CUDA からは gcc が見えない） |
| conda-forge | 推奨: `c-compiler = "*"` + `cxx-compiler = "*"` |

## CUDA 関連エラー診断

| エラー | 原因 | 対処 |
|---|---|---|
| `nvcc not found` | cuda-toolkit 未追加 | `pixi add cuda-toolkit` (12+) / `cuda` (11.x) |
| `gcc: command not found` | gcc 未追加 | `pixi add gcc gxx` |
| nvcc バージョン不一致 | メタパッケージが最新に解決 | `nvidia/label/cuda-{version}` + `cuda = "{version}.*"` |
| `unsupported GNU version!` | gcc が CUDA 上限超過 | 11.x→`gcc = "11.*"`、12.x→`gcc = "12.*"` |
| `CUDA_HOME is not set` | 環境変数未設定 | activation script、または `cuda-toolkit` 追加で自動 |
| `CUDA error: no kernel image` | compute capability 不一致 | torch の CUDA と GPU 世代を確認 |
| `libcudart.so: cannot open` | PyPI と conda の競合 | 片方に統一 |
| `unsupported gpu architecture 'compute_90'` | 古い CUDA で新 GPU | CUDA を上げる |
| `undefined symbol: __cudaRegisterLinkedBinary` | ドライバ不整合 | system-requirements.cuda をドライバに合わせる |

## 環境変数設定

CUDA 拡張ビルド用に activation script で設定:

```toml
[activation]
scripts = ["setup_env.sh"]
```

```bash
# setup_env.sh
export CUDA_HOME=$CONDA_PREFIX
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
```
