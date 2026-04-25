---
name: repo-analyzer
description: リポジトリの依存管理方式を解析し、6-Type分類を行い reports/analysis.json を生成する。/reimplement の Phase 1 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Glob Grep Write
---

# repo-analyzer: リポジトリ解析 + 6-Type 判定

CWD を解析し `reports/analysis.json` に出力。`reports/` は Phase 0 で作成済み。

## Step 1: 依存ファイル検出

```bash
ls environment.yml environment.yaml conda_env.yml conda.yaml 2>/dev/null
ls requirements*.txt 2>/dev/null
ls pyproject.toml setup.py setup.cfg 2>/dev/null
find . -maxdepth 3 -iname "Dockerfile*" 2>/dev/null
```

Dockerfile の検索パスは `analysis.json.dockerfile_search_note` に記録。

## Step 2: defaults チャンネル検出

environment.yml / conda.yaml の `channels:` に `defaults` があれば `pixi_strategy` に記録（Phase 2 で除去）。

## Step 3: submodule 検出（Step 4 より先に実行）

```bash
git submodule status
```

各 submodule を `analysis.json.submodules[]` に記録:

- SSH URL (`git@github.com:`) → HTTPS に変換
- `has_setup_py`: `setup.py` / `pyproject.toml` の有無
- `has_cuda_extension`: `ext_modules` / `CUDAExtension` / `CppExtension` / `CMakeLists.txt` / `.cu` / `.cuh` のいずれか

Phase 2 で `[pypi-dependencies] name = { path, editable = true }` と `no-build-isolation` を注入。

## Step 4: 6-Type 判定

優先順位: A > C > B > E > D > F。

| Type | 条件 |
|---|---|
| A1 | environment.yml のみ、submodule pip deps 行なし |
| A2 | environment.yml + submodule 存在、または pip deps 行あり |
| A3 | environment.yml + requirements*.txt 併存 |
| C1 | pyproject.toml + `[build-system]` = setuptools/hatch/flit |
| C2 | pyproject.toml + `[tool.poetry]` |
| C3 | pyproject.toml + `[tool.pdm]` |
| B1 | `requirements*.txt` 1ファイルのみ、setup.py なし（ファイル名問わず） |
| B2 | `requirements*.txt` 1ファイル + setup.py（ルートまたはサブモジュール） |
| B3 | `requirements*.txt` 複数ファイル |
| E1 | setup.py 単独 |
| E2 | setup.cfg 単独 |
| E3 | setup.py + requirements*.txt（B にフォールバック） |
| D1 | Dockerfile + pip install |
| D2 | Dockerfile + conda install |
| D3 | Dockerfile + apt + pip 混在 |
| F | 依存ファイル皆無 |

B2 判定時、サブモジュールの setup.py は Step 3 の `has_setup_py` を参照。

## Step 5: CUDA / PyTorch バージョン特定

優先度順:

1. environment.yml / requirements.txt の torch 指定
2. Dockerfile の `FROM`（例: `nvidia/cuda:12.1.0-...`）
3. README.md
4. setup.py / pyproject.toml
5. ソース中のバージョンチェック

複数検出時の優先順位: environment.yml > Dockerfile > README。

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

Step 5 の cuda_version と torch version を互換マトリクスと照合。矛盾時は `analysis.json.cuda_torch_compat_mismatch = true` + 推奨値を記録。Phase 2 の attempt 1 は推奨値で開始。

## Step 9.5: GPU アーキテクチャ互換チェック

ホスト GPU の compute capability を取得し、要求 torch+CUDA wheel がそのカーネルを含むか確認。

```bash
nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1  # e.g. "12.0"
```

**原則**: prebuilt wheel はリリース時点の GPU アーキテクチャのカーネルのみ収録。wheel リリース後に登場した GPU 世代では `CUDA error: no kernel image is available` が発生し推論不可。

代表的な閾値:
- compute_cap ≤ 9.0: torch ≥ 2.0 + CUDA ≥ 11.8 で対応済み
- compute_cap ≥ 10.0: その世代を初めてサポートした torch+CUDA が必要

互換問題検出時は `analysis.json.gpu_arch_incompatible` に記録（`cuda_torch_compat_mismatch` と同形式）:

```json
"gpu_arch_incompatible": {
  "detected": true,
  "host_compute_cap": "12.0",
  "max_cc_for_required_torch": "9.0",
  "recommended_torch": "2.7.0",
  "recommended_cuda": "12.8"
}
```

`detected=false` 時は他フィールド省略可。

## Step 10: Feasibility 判定

README / 論文から最低要件を抽出しホスト実測値と突合。`analysis.json.feasibility` に記録。

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
nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1           # compute capability
df -BG --output=avail . | tail -1
nvcc --version 2>/dev/null | grep -oP 'release \K[0-9.]+'
```

判定基準:

- `infeasible`: VRAM 不足かつ CPU fallback 不可 / ディスク不足 / 認証未設定 / 必須 URL が 4xx・5xx
- `degraded`: VRAM 不足だが CPU fallback 可 / URL 到達性のみ警告 / **`gpu_arch_incompatible.detected=true`（推奨アップグレードパスあり）**
- `ok`: 上記に非該当

`gpu_arch_incompatible.detected=true` → `degraded`。Phase 2 attempt 1 から推奨 torch+cuda でビルド試行（`cuda_torch_compat_mismatch` と同フロー）。依存非互換で全 attempt 消化時は Phase 4 で `failed` + `next_actions` に手動手順を記載。

`analysis.json.feasibility`:

```json
{
  "status": "ok|degraded|infeasible",
  "requirements": {"min_vram_gb": 24, "min_disk_gb": null, "min_cuda": "11.8", "needs_auth": false},
  "host": {"vram_gb": 12, "disk_gb": 200, "cuda": "12.1", "gpu_compute_cap": "12.0"},
  "blockers": ["gpu_arch_incompatible: host cc 12.0 > max cc 9.0 for torch 2.1.2+cu118; recommended torch>=2.6+cu128"],
  "has_readme_install_section": true
}
```

`has_readme_install_section`: `grep -niE '^##+ (install|installation|setup|getting started|requirements)' README.md` が 1 件以上ヒットで `true`。Type D/F の依存抽出難度シグナル。

## Step 11: reports/analysis.json 出力

全解析結果を `reports/analysis.json` に出力。スキーマは `/reimplement` の定義に従う。
