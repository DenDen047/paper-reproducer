---
name: usage-documenter
description: 再現が完了したリポジトリの使い方を Quickstart / 発展的使い方 / 開発者向け の 3 段階で抽出し、reports/report.json の usage フィールドを生成する。/reimplement の Phase 4 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Grep Glob
---

# usage-documenter: 多段階の使い方抽出

Phase 4 で呼ばれ、README / スクリプト / Phase 3 の成功コマンドから再現したリポジトリの使い方を 3 段階 (Quickstart / Advanced / Developer) で抽出し、`report.json.usage` を生成する。

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

- `verified: true` は Phase 3 で実行成功したコマンドのみ。それ以外は `false` + `source` に根拠
- 情報が得られなければ `null` (空文字列や架空値で埋めない)
- `advanced` は 0 件可、上限なし

## 抽出手順

### Step 1: Quickstart の決定

優先順位:
1. attempts.tsv から Phase 3 の成功コマンドを取得 → `verified: true`
   ```bash
   awk -F'\t' '$3=="inference" && $5=="success" {print $4}' reports/attempts.tsv | tail -1
   ```
2. 取れなければ `analysis.json.demo_commands[0]` → `verified: false`, source 明記
3. それも無ければ `null`

description は 1 行 (例: "入力画像 1 枚に対して推論を実行")。README 先頭段落 or analysis.json から推定、取れなければ "最小構成での実行"。

### Step 2: Advanced の収集

以下を全部探し、実在確認できたものだけ追加:

a. バッチ処理スクリプト:
```bash
ls scripts/ examples/ demo/ 2>/dev/null
find . -maxdepth 2 -type f \( -name "batch*.py" -o -name "*_batch.py" -o -name "run_all*.py" \) 2>/dev/null
```
title = 「複数入力のバッチ処理」等、command は argparse 定義から具体引数を埋める。

b. WebUI:
```bash
grep -l -rE "gradio|streamlit|flask|fastapi" --include="*.py" . 2>/dev/null | head -5
ls app.py webui.py web_demo.py 2>/dev/null
```
title = 「WebUI ({framework})」、既知ポート (gradio: 7860, streamlit: 8501) を note に。

c. README の Usage / Advanced / Examples 節:
```bash
grep -n -iE "^##+ (usage|examples?|advanced|batch|inference|demo)" README.md 2>/dev/null
```
(a)(b) でカバーしていないコマンドのみ追加。スクリプト実在を `ls` で確認。

各エントリの `source` に根拠を明記 (例: `"README.md #Usage"`, `"scripts/batch_infer.py"`)。

GUI 依存静的スキャン: 対象スクリプトが `cv2.imshow` / `plt.show()` / `open3d.visualization` / `tkinter` を直接呼ぶ場合は note に「headless 環境ではデフォルトで描画がスキップされます」と明記。

Auto-verify (任意): advanced の先頭 1–2 件を 60s タイムアウトで実行し、exit 0 なら `verified: true` に昇格、失敗なら note に `"verify failed: {要約}"`。`--help` / 最小入力 / dry-run を優先して OOM を避ける。

### Step 3: Developer サンプル

目的: 別アプリから import して使う方法を示す。

1. トップレベル package を検出:
   ```bash
   grep -E "^(name|packages)" setup.py pyproject.toml 2>/dev/null
   find . -maxdepth 3 -name "__init__.py" -not -path "./.pixi/*" | head -5
   ```
2. 主要なクラス/関数を grep (`class `/`def `)。典型: `Model`, `Predictor`, `Pipeline`, `{PaperName}`。
3. 実機検証:
   ```bash
   pixi run python -c "import {package}; print({package}.__all__)" 2>/dev/null
   ```
   成功した候補のみ `import_path` に採用。
4. sample_code は 5–10 行の最小コード。重み/入力ロードは Quickstart 実装を参照。未確認の関数/メソッドは **書かない**。不明箇所は `# TODO: set your input` でコメント化。
5. どの候補も import 失敗 or 公開 API 未発見なら `developer: null`。

## ハルシネーション対策

以下のどれかで検証できない情報は出力しない:

| 対象 | 検証方法 |
|---|---|
| スクリプトファイル名 | `ls {path}` |
| import パス | `pixi run python -c "import X"` |
| 関数/クラスシグネチャ | ソース内を grep |
| 引数デフォルト値 | argparse 定義を直接読む |
| WebUI ポート | `.launch(server_port=...)` / `.run(port=...)` を grep |

検証不能なら該当フィールドを `null` またはエントリを省略。

## status 別フォールバック

| status | 挙動 |
|---|---|
| `success` | Quickstart は Phase 3 コマンド (verified)、Advanced/Developer は通常 |
| `partial` | 成功分だけ verified、他は通常 |
| `failed` | Quickstart は README ベース (`verified: false`)、Developer は `null` 可、Advanced は取れるだけ。各 note に「再現失敗のため動作保証なし」 |

## 呼び出し元との契約

JSON 生成のみ担当。HTML レンダリングは呼び出し元 (Phase 4 Step 1.5) が行う (責務分離)。
