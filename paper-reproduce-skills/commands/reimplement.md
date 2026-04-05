---
description: CV論文のGitHubリポジトリを全自動再現する。CWD=clone済みリポジトリで実行。
allowed-tools: Bash Read Write Edit Glob Grep Agent
---

# /reimplement — 論文リポジトリ全自動再現コマンド

あなたは CV 論文の GitHub リポジトリを Pixi 環境で全自動再現するエージェントです。
以下の Phase を順番に実行してください。**NEVER STOP**: 人間に「続けますか？」と聞かない。失敗しても自律的にリトライし続ける。手動停止されるまで止まらない。

---

## Phase 0: Initialize

1. `git status` で CWD が git リポジトリであることを確認
2. `git stash` で未コミット変更を退避（あれば）
3. リポジトリ名・URL を `git remote -v` から自動検出
4. `git submodule status` で submodule の有無を確認
5. attempts.tsv を初期化（ヘッダー行のみ書き込み）:
   ```
   attempt\tcommit\tphase\taction\tresult\terror_tier\terror_summary\tduration_s
   ```
6. `ls` で依存ファイル一覧を取得（Phase 1 の事前情報）
7. `.gitignore` に `attempts.tsv` を追加（git 管理外にする）

---

## Phase 1: リポジトリ解析

**repo-analyzer スキルを参照して実行。**

1. README.md を読む
2. 依存ファイルを特定し、6-Type 分類で判定（下記参照）
3. CUDA / PyTorch バージョンを特定
4. submodule を検出し、SSH URL は HTTPS に変換
5. C++/CUDA 拡張の有無を検出（no-build-isolation 候補）
6. defaults チャンネルの混入を検出
7. モデルダウンロード方法を特定
8. デモ/推論コマンドを特定
9. 難易度評価（easy/medium/hard）
10. 結果を `analysis.json` として出力

### 6-Type 分類（判定優先順位）

| 優先順位 | Type | 依存ファイル | 変換戦略 |
|---------|------|-------------|---------|
| 1 | A | environment.yml / conda.yaml | `pixi init --import` + Divide-and-Conquer |
| 2 | C | pyproject.toml | `pixi init --pyproject` |
| 3 | B | requirements.txt | `pixi init` + pypi-dependencies |
| 4 | E | setup.py / setup.cfg | deps 抽出 → pypi-dependencies (E3: requirements.txt 併存時は Type B にフォールバック) |
| 5 | D | Dockerfile のみ | 命令解析 → Type A/B に合流 |
| 6 | F | 依存ファイルなし | import 解析 + ソースマイニング |

### Type 判定フローチャート

```
environment.yml exists?
  YES → requirements.txt も存在? → YES: A3 / NO: submodule pip deps? → YES: A2 / NO: A1
  NO  → pyproject.toml exists?
    YES → [tool.poetry]? → YES: C2 / NO: [tool.pdm]? → YES: C3 / NO: C1
    NO  → requirements.txt exists?
      YES → setup.py exists? → YES: B2 / NO: 複数req files? → YES: B3 / NO: B1
      NO  → setup.py/setup.cfg exists?
        YES → requirements.txt exists? → YES: E3 (→Type B) / NO: E1/E2
        NO  → Dockerfile exists?
          YES → pip in Dockerfile? → YES: D1 / conda? → YES: D2 / NO: D3
          NO  → F
```

### analysis.json のスキーマ

```json
{
  "repo_name": "string",
  "repo_url": "string",
  "dep_type": "A1|A2|A3|B1|B2|B3|C1|C2|C3|D1|D2|D3|E1|E2|E3|F",
  "dep_type_label": "string",
  "dep_files_found": {
    "environment_yml": "string|null",
    "requirements_txt": ["string"],
    "pyproject_toml": "string|null",
    "setup_py": "boolean",
    "setup_cfg": "boolean",
    "dockerfile": "string|null",
    "conda_yaml": "string|null"
  },
  "python_version": "string",
  "cuda_version": "string|null",
  "pytorch_version": "string|null",
  "submodules": [
    {
      "name": "string",
      "path": "string",
      "url": "string",
      "has_cuda_extension": "boolean"
    }
  ],
  "needs_no_build_isolation": ["string"],
  "demo_commands": ["string"],
  "model_download": {
    "method": "wget|gdown|huggingface|script",
    "details": "string"
  },
  "pixi_strategy": {
    "init_method": "pixi init --import|pixi init|pixi init --pyproject",
    "channels": ["string"],
    "torch_source": "pypi_wheel|conda_pytorch",
    "cuda_channel": "conda-forge|nvidia",
    "needs_divide_and_conquer": "boolean",
    "needs_no_build_isolation": ["string"],
    "needs_dep_conversion": "boolean",
    "conversion_source": "string|null"
  },
  "dockerfile_analysis": {
    "base_image": "string|null",
    "cuda_from_image": "string|null",
    "apt_packages": ["string"],
    "pip_commands": ["string"],
    "env_vars": {}
  },
  "difficulty": "easy|medium|hard"
}
```

---

## Phase 2: Pixi 環境構築

**pixi-env-builder スキル、dep-converter スキル、cuda-dependency-resolver スキルを参照して実行。**

analysis.json の `dep_type` に基づいて変換戦略を選択し、pixi.toml を生成する。

### Type A (conda系) のフロー

- **A1**: `pixi init --import environment.yml` → defaults 除去 → `pixi install`
- **A2**: environment.yml から submodule 行を除去 → cleaned.yml を作成 → `pixi init --import cleaned.yml` → defaults 除去 → ベースで `pixi install` → submodule を1つずつ pypi-dependencies に追加 → no-build-isolation 設定 → 完了後 cleaned.yml を削除
- **A3**: A2 と同様 + requirements.txt の差分を pypi-deps に追加

### Type B (pip系) のフロー

**dep-converter スキルの requirements.txt パースルールに従って変換。**

- **B1**: `pixi init` → requirements.txt を dep-converter ルールで `[pypi-dependencies]` に変換 → PyTorch は `extra-index-urls` で CUDA wheel を指定 → `pixi install`
- **B2**: B1 + プロジェクト自体を `{ path = ".", editable = true }` で追加
- **B3**: `_dev` / `_test` ファイルを除外して残りを統合 → B1 のフローへ

### Type C (pyproject.toml系) のフロー

- **C1**: `pixi init --pyproject` → `[tool.pixi]` セクションを設定 → プロジェクトを editable install → `pixi install`
- **C2**: Poetry のバージョン記法を PEP 440 に変換（dep-converter 参照）→ C1 のフローへ
- **C3**: PDM は PEP 621 準拠なので C1 と同じフロー

### Type E (setup.py/setup.cfg系) のフロー

- **E1**: AST パースで `install_requires` を抽出 → Type B の変換フローへ + editable install
- **E2**: setup.cfg の `[options]` から `install_requires` を読み → E1 と同じ
- **E3**: requirements.txt を優先して Type B として処理、setup.py は editable install にのみ使用

### Type D (Dockerfile系) のフロー

**dep-converter スキルの Dockerfile パースルールに従って変換。**

- **D1**: Dockerfile の `pip install` コマンドを解析 → パッケージリストを抽出 → Type B のフローに合流。`FROM` からCUDA バージョン推定、`apt-get install` は conda-forge マッピングで変換
- **D2**: Dockerfile の `conda install` コマンドを解析 → チャンネルとパッケージを抽出 → Type A のフローに合流
- **D3**: apt 依存を conda-forge マッピングで `[dependencies]` に、pip 依存を `[pypi-dependencies]` に変換。`ENV` の環境変数は `[activation]` scripts に変換

### Type F (依存ファイルなし) のフロー

- **F**: README.md の Installation セクションからコマンド抽出 → ソースコードの import 文を全スキャン → 標準ライブラリ除外 → import 名→PyPI パッケージ名マッピング（dep-converter 参照）→ `pixi init` → 推定 deps を `[pypi-dependencies]` に追加 → `pixi install` → エラーから不足パッケージを反復追加

### 共通処理（全 Type で適用する denkiwakame ルール）

1. **defaults チャンネル除去**: channels から "defaults" を削除
2. **CUDA 統一**: PyPI wheel の場合は cuda-toolkit、conda の場合は `cuda` メタパッケージ + gcc/gxx も追加（cuda-dependency-resolver スキル参照）
3. **system-requirements.cuda 設定**: ホストドライバ要件の申告
4. **submodule → pypi-dependencies 変換**: editable install + no-build-isolation
5. **Divide-and-Conquer**: ベース deps だけで通す → submodule を1つずつ追加
6. **gcc/gxx を pixi 管理下に**: nvidia channel 使用時は必須

### Experiment Loop（NEVER STOP）

**experiment-loop スキルを参照して実行。**

```
while not succeeded:
  1. START_TIME=$(date +%s)  ← 省略禁止
  2. pixi.toml を生成/修正
  3. git add pixi.toml && git commit -m "attempt #{n}: {action}"
  4. pixi install 2>&1 | tee build.log
  5. END_TIME=$(date +%s) && DURATION=$((END_TIME - START_TIME))  ← 省略禁止
  6. attempts.tsv にログ追記（成功でも失敗でも必ず記録）  ← 省略禁止
  7. 結果判定:
     成功 → advance + 環境検証 (python -c "import torch; print(torch.cuda.is_available())")
     失敗 → diagnose + classify:
       Tier 1 (Trivial Fix): auto-fix → retry
       Tier 2 (Strategy Change): 戦略変更 → rebuild
       Tier 3 (Fundamental Rethink): Type変更 or report
  8. 失敗時: git reset --hard HEAD~1
```

**CRITICAL: ステップ1, 5, 6 は成功・失敗を問わず毎回必ず実行する。attempts.tsv への記録漏れは禁止。**

---

## Phase 3: 推論実行

**experiment-loop スキルを参照して実行。**

### Step 1: モデルダウンロード

analysis.json の `model_download` に基づいてモデルをダウンロード:

| method | 実行方法 |
|--------|---------|
| `wget` | `pixi run python -c "import urllib.request; ..."` or `wget` コマンド |
| `gdown` | `pixi run gdown {file_id} -O {output_path}` |
| `huggingface` | `pixi run python -c "from huggingface_hub import hf_hub_download; ..."` |
| `script` | README 記載のダウンロードスクリプトを実行 |

**gdown --folder の注意（二重ネスト問題）:**
- `gdown --folder URL -O /workspace/weights/` は `/workspace/weights/weights/` になる
- 回避策: 一時ディレクトリにダウンロード後、中身を目的のパスに移動:
  ```bash
  pixi run gdown --folder {url} -O /tmp/dl_tmp/
  mv /tmp/dl_tmp/*/* {target_path}/
  rm -rf /tmp/dl_tmp
  ```

**ダウンロード失敗時:**
- URL が切れている → README の代替リンクを探す、HuggingFace Hub を検索
- 認証が必要 → Tier 3 としてレポートに記載
- 容量が大きすぎる → 軽量版モデルがあれば代替

### Step 2: Headless GUI 対策

Docker コンテナ内は headless 環境。CV 論文は GUI コードを含むことが多いため、実行前にモンキーパッチを適用:

**cv2 の GUI 関数をモック:**
```python
import cv2
cv2.imshow = lambda *a, **kw: None
cv2.waitKey = lambda *a, **kw: 0
cv2.destroyAllWindows = lambda: None
cv2.namedWindow = lambda *a, **kw: None
```

**open3d の可視化をモック:**
```python
# open3d.visualization 使用時
import open3d as o3d
if hasattr(o3d, 'visualization'):
    o3d.visualization.draw_geometries = lambda *a, **kw: None
```

**matplotlib のバックエンド設定:**
```python
import matplotlib
matplotlib.use('Agg')  # 非 GUI バックエンド
```

**適用方法:** 対象スクリプトの先頭に monkey-patch を挿入するラッパースクリプトを作成するか、対象スクリプトを直接編集（git commit で記録）。

### Step 3: デモ/推論スクリプト実行

```bash
START_TIME=$(date +%s)
pixi run python {demo_command} 2>&1 | tee inference.log
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
```

### Step 4: 失敗時の段階的フォールバック

**Tier 1: Trivial Fix（自動修正して即リトライ）**

| エラー | 自動修正 |
|--------|---------|
| `ModuleNotFoundError: {module}` | `pixi add --pypi {module}` して再実行 |
| `FileNotFoundError` (モデルファイル) | Step 1 のダウンロードを再試行 |
| `cv2.error: ... display` | Step 2 の headless 対策を適用 |
| `ImportError: cannot import name ...` | バージョンを調整して再インストール |

**Tier 2: OOM 5段階フォールバック**

GPU メモリ不足（`CUDA out of memory` / `RuntimeError: CUDA error`）時の段階的対策:

```
Step 1: torch.cuda.empty_cache() を推論前に追加
Step 2: batch_size を半減（コマンドライン引数 or コード内定数を変更）
Step 3: 入力解像度を半減（--resolution, --img_size 等）
Step 4: with torch.no_grad() + torch.cuda.amp.autocast() を適用
Step 5: CPU fallback（CUDA_VISIBLE_DEVICES="" で再実行）
```

各ステップで pixi.toml ではなくスクリプトやコマンドライン引数を変更する。git commit で変更を記録。

**Tier 3: 根本的問題（レポートに記載）**

| エラー | 対応 |
|--------|------|
| 特定 GPU アーキテクチャ必須 | CPU fallback を試し、それも失敗ならレポート |
| データセットが非公開 / 巨大 | サンプルデータで代替を試みる。不可��らレポート |
| 認証が必要（API key 等） | レポートに手動設定の指示を記載 |
| SegmentationFault | レポートに記載 |

### Step 5: attempts.tsv にログ追記

**CRITICAL: 成功・失敗を問わず毎回必ず記録する。**

```bash
COMMIT=$(git rev-parse --short HEAD)
echo -e "${ATTEMPT}\t${COMMIT}\tinference\t${ACTION}\t${RESULT}\t${TIER}\t${SUMMARY}\t${DURATION}" >> attempts.tsv
```

### Experiment Loop (Phase 3)

```
while not inference_succeeded:
  1. START_TIME=$(date +%s)  ← 省略禁止
  2. スクリプト修正 or パラメータ変更
  3. git add -A && git commit -m "attempt #{n}: {action}"
  4. pixi run python {demo_command} 2>&1 | tee inference.log
  5. END_TIME=$(date +%s) && DURATION=$((END_TIME - START_TIME))  ← 省略禁止
  6. attempts.tsv にログ追記  ← 省略禁止
  7. 結果判定:
     成功（出力ファイルが生成された）→ Phase 4 へ
     失敗 → diagnose + classify:
       Tier 1: auto-fix → retry
       Tier 2: OOM fallback → retry
       Tier 3: report に記載 → Phase 4 へ（status = partial or failed）
  8. 失敗時: git reset --hard HEAD~1
```

---

## Phase 4: レポート生成

1. 中間ファイルのクリーンアップ: cleaned.yml 等の一時ファイルを削除
2. `report.json` 生成（機械可読）:
   ```json
   {
     "repo_name": "string",
     "repo_url": "string",
     "status": "success|partial|failed",
     "dep_type": "string",
     "total_attempts": "number",
     "duration_total_s": "number",
     "pixi_toml_hash": "string",
     "inference_output": "string|null",
     "errors": ["string"]
   }
   ```
   **status の判定基準:**
   - `success`: pixi install 成功 + 推論実行成功（出力ファイルが生成された）
   - `partial`: pixi install 成功 + 推論未実行（データセット不在等）、または pixi install 成功 + 推論一部成功
   - `failed`: pixi install 失敗、または推論が根本的に動作しない
3. `report.html` 生成（目視確認用）— **必ず attempts.tsv を読み込んで試行履歴テーブルを生成すること**。report.html の試行数と attempts.tsv の行数は一致しなければならない。
4. 最終状態の pixi.toml + pixi.lock を保持

---

## 核心原則

### NEVER STOP
- 環境構築に失敗しても止まらない — Tier 分類に従って自律的に修正・再試行
- 推論に失敗しても止まらない — OOM フォールバック → パラメータ変更 → CPU fallback
- 唯一の停止条件: 全 Phase 完了、または人間による手動停止

### denkiwakame ワークフロー準拠
- **Divide-and-Conquer**: submodule は最初に除外し、ベース構築後に1つずつ追加
- **no-build-isolation**: PEP517 違反の submodule (C++/CUDA 拡張) に必須
- **CUDA は1つに統一**: wheel/conda/docker/host の4つが混在するサバンナを整理
- **defaults チャンネル除去**: miniconda 由来で混入しがちだが有償かつ不要
- **conda-forge を基本チャンネル**: ただし元 repo が conda pytorch を使う場合は pytorch/nvidia チャンネルも許容
- **gcc/gxx も pixi 管理下に**: nvidia channel の CUDA では gcc/g++ が外側から見えない
- **system-requirements.cuda**: ホストドライバ要件の申告であり、pixi 環境内の CUDA バージョンとは別物
