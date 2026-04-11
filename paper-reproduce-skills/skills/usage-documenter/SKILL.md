---
name: usage-documenter
description: 再現が完了したリポジトリの使い方を Quickstart / 発展的使い方 / 開発者向け の 3 段階で抽出し、reports/report.json の usage フィールドを生成する。/reimplement の Phase 4 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Grep Glob
---

# usage-documenter: 多段階の使い方抽出

`/reimplement` の Phase 4 で呼び出される。Phase 3 が終了した時点のリポジトリ状態を使い、README・スクリプト群・実行済みコマンドから**再現した論文リポジトリの使い方**を 3 段階で抽出し、`reports/report.json` の `usage` オブジェクトを生成する。

## 出力スキーマ

```json
{
  "usage": {
    "quickstart": {
      "description": "string",
      "command": "string",
      "verified": "boolean",
      "note": "string|null"
    } | null,
    "advanced": [
      {
        "title": "string",
        "command": "string",
        "verified": "boolean",
        "source": "string",
        "note": "string|null"
      }
    ],
    "developer": {
      "description": "string",
      "sample_code": "string",
      "import_path": "string",
      "note": "string|null"
    } | null
  }
}
```

- `verified: true` は Phase 3 で実行成功した情報のみ。それ以外は `false` + `source` に根拠を明記
- 情報が得られない場合は `null` にする（空文字列や架空の値で埋めない）
- `advanced` は配列。個数に上限なし、情報がなければ空配列 `[]`

## 抽出手順

### Step 1: Quickstart の決定

**優先順位:**

1. **`reports/attempts.tsv` から Phase 3 の成功コマンドを抽出**
   ```bash
   awk -F'\t' '$3=="inference" && $5=="success" {print $4}' reports/attempts.tsv | tail -1
   ```
   取れたらそれが Quickstart。`verified: true` とする。

2. **取れなければ** `reports/analysis.json` の `demo_commands[0]` を使う。`verified: false`, `source: "analysis.json の demo_commands"`

3. **それも無ければ** Quickstart は `null`

**description の書き方:** リポジトリが何をするかを 1 行で表現する（例: "入力画像 1 枚に対して推論を実行"）。README の先頭段落や `analysis.json` の情報から推定する。推定できなければ "最小構成での実行" のような汎用文言。

### Step 2: Advanced の収集

以下を **すべて** 検索し、存在確認できたものだけ配列に追加する:

**a. バッチ処理系スクリプト**
```bash
ls scripts/ examples/ demo/ 2>/dev/null
find . -maxdepth 2 -type f \( -name "batch*.py" -o -name "*_batch.py" -o -name "run_all*.py" \) 2>/dev/null
```
見つかったら title を「複数入力のバッチ処理」等に、command を `pixi run python {path}` の雛形にする（ただし実際の引数は README か script の `argparse` 定義から取る）。

**b. WebUI**
```bash
grep -l -rE "gradio|streamlit|flask|fastapi" --include="*.py" . 2>/dev/null | head -5
ls app.py webui.py web_demo.py 2>/dev/null
```
見つかったら title を「WebUI ({framework})」とし、起動コマンド + 既知ポート（gradio: 7860, streamlit: 8501）を note に記載。

**c. README の Usage / Advanced / Examples セクション**
```bash
grep -n -iE "^##+ (usage|examples?|advanced|batch|inference|demo)" README.md 2>/dev/null
```
該当セクションを読み、記載されているコマンド例のうち **(a)(b) でカバーしていないもの** を追加。ただし該当スクリプトが実在することを `ls` で確認する。

**各エントリの `source` フィールドに根拠を明記する**（例: `"README.md #Usage"`, `"scripts/batch_infer.py"`）。

### Step 3: Developer 向けサンプルの抽出

**目的:** このリポジトリを別アプリから import して使う方法を示す。

**手順:**

1. **import 可能なトップレベルエクスポートを検出**
   ```bash
   # setup.py / pyproject.toml から package 名を推定
   grep -E "^(name|packages)" setup.py pyproject.toml 2>/dev/null

   # もしくは __init__.py を直接見る
   find . -maxdepth 3 -name "__init__.py" -not -path "./.pixi/*" | head -5
   ```

2. **各候補 package で主要なクラス/関数を探す**
   ```bash
   grep -nE "^(class|def) " {package}/__init__.py 2>/dev/null
   ```
   典型的なパターン: `Model`, `Predictor`, `Pipeline`, `{PaperName}` などのクラス。

3. **import を実機検証**
   ```bash
   pixi run python -c "import {package}; print({package}.__all__)" 2>/dev/null
   ```
   成功したら `import_path` を確定。失敗したら該当候補を捨てて次を試す。

4. **sample_code の生成**
   - 確定した import path を使い、5〜10 行の最小コードを構築
   - 重み/入力のロード方法は **Quickstart コマンドの実装** を参照して書く（argparse のデフォルト値、設定ファイル等）
   - **絶対に** 未確認の関数名やメソッドシグネチャを書かない。確認できない部分は `# TODO: set your input` のようにコメントで明示

5. **どの候補も import に失敗する**、または `__init__.py` に公開 API が見当たらない場合は `developer: null` とし、報告する。

## ハルシネーション対策（CRITICAL）

**以下のいずれかで検証できない情報は出力しない:**

| 対象 | 検証方法 |
|---|---|
| コマンド中のスクリプトファイル名 | `ls {path}` で存在確認 |
| Python の import パス | `pixi run python -c "import X"` が成功する |
| 関数/クラスシグネチャ | ソース内を grep で実在確認 |
| 引数のデフォルト値 | argparse 定義を直接読む |
| WebUI のポート番号 | コード内の `.launch(server_port=...)` / `.run(port=...)` を grep |

**検証できない情報は `null` または該当エントリを省略する**。

## ステータス別フォールバック

| Phase 3 status | 挙動 |
|---|---|
| `success` | Quickstart は Phase 3 コマンドから（`verified: true`）、Advanced/Developer は通常フロー |
| `partial` | 成功した部分だけ `verified: true`、その他は通常フロー |
| `failed` | Quickstart は README ベース（`verified: false`）、Developer はスキップ傾向（`null` も可）、Advanced は README/scripts から取れるだけ取る。全体として「再現失敗のため動作保証なし」を各 `note` に明示 |

## 出力の保存

生成した `usage` オブジェクトは `/reimplement` Phase 4 Step 1.5 の呼び出し元に返す。呼び出し元は Step 2 で `reports/report.json` に組み込み、Step 3 で HTML にレンダリングする。

このスキルは JSON 生成までを担当し、HTML レンダリングは行わない（責務分離）。
