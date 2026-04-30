---
name: usage-documenter
description: 再現が完了したリポジトリの使い方を Quickstart / 発展的使い方 / 開発者向け の 3 段階で抽出し、reports/report.json の usage フィールドを生成する。/reimplement の Phase 4 で自動参照される。
user-invocable: false
allowed-tools: Bash Read Grep Glob
---

# usage-documenter: 多段階の使い方抽出

README / スクリプト / Phase 3 の成功コマンドから使い方を 3 段階（Quickstart / Advanced / Developer）で抽出し、`report.json.usage` を生成する。

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

- `verified: true` は Phase 3 実行成功のみ
- 情報が得られなければ `null`（空文字や架空値で埋めない）
- `advanced` は 0 件可、上限なし

## Step 1: Quickstart

優先順位:

1. attempts.tsv から Phase 3 成功コマンド → `verified: true`
   ```bash
   awk -F'\t' '$3=="phase3" && $6=="success" {print $4}' reports/attempts.tsv | tail -1
   ```
2. なければ `analysis.json.demo_commands[0]` → `verified: false` + source
3. なければ `null`

description は 1 行（例: 「入力画像 1 枚に対して推論を実行」）。README 先頭段落 or `analysis.json` から推定。取れなければ「最小構成での実行」。

## Step 2: Advanced

以下を全部探し、実在確認できたものだけ追加。

**バッチ処理スクリプト**:
```bash
ls scripts/ examples/ demo/ 2>/dev/null
find . -maxdepth 2 -type f \( -name "batch*.py" -o -name "*_batch.py" -o -name "run_all*.py" \) 2>/dev/null
```

title は「複数入力のバッチ処理」等、command は argparse 定義から具体引数を埋める。

**WebUI**:
```bash
grep -l -rE "gradio|streamlit|flask|fastapi" --include="*.py" . 2>/dev/null | head -5
ls app.py webui.py web_demo.py 2>/dev/null
```

title は「WebUI ({framework})」、既知ポート（gradio: 7860、streamlit: 8501）を note に。

**README の Usage / Advanced / Examples 節**:
```bash
grep -n -iE "^##+ (usage|examples?|advanced|batch|inference|demo)" README.md 2>/dev/null
```

上記でカバーしていないコマンドのみ追加、スクリプトを `ls` で実在確認。

各エントリの `source` に根拠明記（例: `README.md #Usage`、`scripts/batch_infer.py`）。

**GUI 依存静的スキャン** (`cv2.imshow` / `plt.show()` / `open3d.visualization` / `tkinter`):
- 該当エントリに `gui_dependency: true` を付与
- note に「headless 環境では描画スキップ」を明記
- Auto-verify 時: `PYTHONSTARTUP=/etc/headless_patches/headless_patch.py pixi run ...` で起動
- patch 適用で exit 0 → `verified: true` + note に「headless patch 適用」

**Auto-verify（任意）**: advanced 先頭 1–2 件を 60s タイムアウトで実行し、exit 0 なら `verified: true` に昇格、失敗なら note に `verify failed: {要約}`。`--help` / 最小入力 / dry-run を優先して OOM を避ける。

## Step 3: Developer サンプル

目的: 別アプリから import して使う方法。

1. トップレベル package 検出:
   ```bash
   grep -E "^(name|packages)" setup.py pyproject.toml 2>/dev/null
   find . -maxdepth 3 -name "__init__.py" -not -path "./.pixi/*" | head -5
   ```
2. 主要なクラス/関数を grep（典型: `Model`, `Predictor`, `Pipeline`, `{PaperName}`）
3. 実機検証:
   ```bash
   pixi run python -c "import {package}; print({package}.__all__)" 2>/dev/null
   ```
   成功した候補のみ `import_path` に採用
4. sample_code は 5–10 行の最小コード。重み/入力ロードは Quickstart 実装を参照。未確認の関数/メソッドは書かない。不明箇所は `# TODO: set your input`
5. 全候補で import 失敗 or 公開 API 未発見なら `developer: null`

## ハルシネーション対策

以下のどれかで検証できない情報は出さない:

| 対象 | 検証方法 |
|---|---|
| スクリプトファイル名 | `ls {path}` |
| import パス | `pixi run python -c "import X"` |
| 関数/クラスシグネチャ | ソース grep |
| 引数デフォルト値 | argparse 定義を直接読む |
| WebUI ポート | `.launch(server_port=...)` / `.run(port=...)` を grep |

検証不能なら該当フィールドを `null` またはエントリ省略。

## status 別挙動

| status | 挙動 |
|---|---|
| `success` | Quickstart は Phase 3 コマンド (verified)、Advanced/Developer は通常 |
| `partial` | 成功分のみ verified |
| `failed` | Quickstart は README ベース (`verified: false`)、Developer は `null` 可、Advanced は取れるだけ。各 note に「再現失敗のため動作保証なし」 |

## 契約

JSON 生成のみ担当。HTML レンダリングは呼び出し元（Phase 4 Step 1.5）が行う。
