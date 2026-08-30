---
name: webui-builder
description: 再現に成功した推論コマンドを包む Gradio 推論 WebUI (reports/webui/) を生成しスモークテストする。/reimplement の Phase 4 Step 1.65 から自動参照される。
user-invocable: false
allowed-tools: Bash Read Write Edit Glob Grep
---

# webui-builder: 検証済み推論コマンドの WebUI 化

Phase 3 で実際に成功した推論コマンドを、非エンジニアでも使える Gradio WebUI に包む。

## 設計 (何を生成し、何を生成しないか)

- **app.py は固定テンプレート** (`/paper-reproduce-skills/templates/webui/app.py` をそのままコピー)。**編集は MUST NOT** — repo 固有の情報はすべて `webui.json` に載せる (schema: `/paper-reproduce-skills/schemas/webui.schema.json`)。
- **CLI ラッパー方式**: 推論はリクエストごとに検証済みコマンドを subprocess 実行する (repo の pixi 環境)。モデル常駐化・import ベースの独自アプリ生成は **MUST NOT** (repo ごとに壊れ、検証コストが跳ねる)。
- **WebUI の pixi 環境は repo と分離** (`reports/webui/pixi.toml`、gradio のみ)。論文環境に gradio を追加するのは **MUST NOT** (fastapi / pydantic 系の依存衝突源)。
- サーバーの常駐起動はしない。起動は呼び出し元 (reimplement Phase 4 Step 7 / `scripts/serve.sh` / `bootstrap.sh --serve`) の責務。

## 起動条件

以下を**すべて**満たすときだけ生成する。満たさない場合は skip し、`webui` オブジェクトに `{generated: false, smoke_test: "skipped", reason: "<なぜ>"}` を記録して呼び出し元へ返る (NEVER STOP):

1. `report.json.status` (Step 2 判定値) が `success` または `partial`
2. Phase 3 の成功推論コマンドが存在する (`attempts.tsv` の phase3 / result=success / intent に `P0-E paper-default attempt` を含む行、または `usage.quickstart.verified == true`)
3. そのコマンドがファイル入力 → ファイル出力の形に還元できる (対話型 REPL 専用・学習専用 repo は skip)

## Step 1: コマンドテンプレート化

検証済みコマンド (上記 2 の行の `action` 列 / `usage.quickstart.command`) を `command_template` に変換する:

1. **入力パスの置換**: コマンド中の入力ファイル/ディレクトリ引数を `{input}` 等のプレースホルダーに置換。どの引数が入力かは `report.json.samples.items[].input_paths` と実コマンドの突き合わせで特定する
2. **出力先の置換**: 出力ディレクトリ引数 (`--output_dir` / `--out` / `-o` 等) が argparse / `reports/_paper_default_args.json` で確認できれば `{output_dir}` に置換。**出力先引数が無い repo では置換しない** — その場合 app.py は workdir 相対 glob + mtime フィルタで出力を収集する (固定出力パスモード)
3. **他の引数は一切変えない** (P0-E: 論文デフォルトのまま。縮小・省略は MUST NOT)
4. `workdir` はコンテナ内 repo ルートの絶対パス (`/workspaces/<repo>`)
5. `timeout_s` は Phase 3 実測 (`report.json.inference_runtime_s` または該当 attempt の `duration_s`) の **3 倍以上** (最低 600)

## Step 2: 入出力タイプの決定

`report.json.samples.category` から機械的にマップする (実出力と食い違う場合のみ実態に合わせて調整し、理由を webui.json の `description` に一言残す):

| samples.category | inputs[].type | outputs[].type |
|---|---|---|
| `rgb_to_rgb`, `mono_to_depth`, `image_to_mask`, `image_to_bbox`, `image_to_keypoint` | `image` | `gallery` |
| `stereo_to_depth`, `frames_to_flow` | `files` | `gallery` |
| `mv_to_gaussians`, `mv_to_nerf` | `files` | `video` (+ `file` で生データ) |
| `images_to_pointcloud`, `image_to_mesh` | `image` または `files` | `model3d` |
| `video_output` | 入力実態に合わせる | `video` |
| `unknown` | `file` | `file` |

- `outputs[].glob`: **Phase 3 の実出力ファイルが match することを必ず確認する** (`{output_dir}` モードなら出力 dir 内の相対 glob、固定出力パスモードなら workdir 相対 glob)。拡張子は実出力に合わせ、憶測で書かない
- `model3d` は Gradio Model3D が表示できる拡張子 (`.glb` / `.gltf` / `.obj` / `.stl` / `.ply` / `.splat`) のみ。表示不能な形式は `file` に落とす
- `example_input`: `reports/samples/input/` の実在ファイル (workdir 相対) を 1 つ設定。単一入力 UI のときだけ表示される

## Step 3: 生成 + schema gate

```bash
mkdir -p reports/webui
# webui.json を書いたら必ず schema validate (P0-D と同じ流儀)
check-jsonschema --schemafile /paper-reproduce-skills/schemas/webui.schema.json reports/webui/webui.json
cp /paper-reproduce-skills/templates/webui/app.py    reports/webui/app.py
cp /paper-reproduce-skills/templates/webui/pixi.toml reports/webui/pixi.toml
# 実行時生成物は git / アーカイブに入れない
grep -qxF 'reports/webui/.pixi/' .gitignore || cat >> .gitignore <<'EOF'
reports/webui/.pixi/
reports/webui/jobs/
EOF
```

schema 違反は Tier 2-config として webui.json を修正して再検証 (2 回まで)。

## Step 4: pixi 環境構築 + スモークテスト

```bash
(cd reports/webui && pixi install)          # ネットワーク失敗は Tier 1 (2 回まで再試行)
(cd reports/webui && timeout 300 pixi run python app.py --smoke)
```

`--smoke` は起動 → HTTP 200 確認 → 終了まで app.py が自前で行う (exit 0 = passed)。

- 成功 → `webui.smoke_test = "passed"`
- 失敗 → ログを読み webui.json 起因 (Tier 2-config) なら修正して 1 回だけ再試行。それでも失敗なら `{generated: false, smoke_test: "failed", reason: "<エラー要約>"}` で確定し先へ進む (NEVER STOP)。**スモーク未通過のまま `generated: true` にするのは MUST NOT**
- スモークテストは UI 起動の検証であり推論は走らせない (推論コマンド自体は Phase 3 で検証済み。GPU 再消費はしない)

## Step 5: report.json への反映

Phase 4 Step 2 で `report.json` に組み込む値を返す:

**(1) `webui` オブジェクト** (schema: `schemas/report.schema.json` の `webui`):

```json
{
  "generated": true,
  "config_path": "reports/webui/webui.json",
  "port": 7860,
  "smoke_test": "passed",
  "reason": null
}
```

skip / 失敗時は `{"generated": false, "config_path": null, "port": null, "smoke_test": "skipped|failed", "reason": "<必ず記録>"}`。

**(2) `usage.advanced` に 1 エントリ追加** (generated: true のときのみ):

- `title`: `$REPORT_LANG` に従い「推論 WebUI (自動生成)」 / "Inference WebUI (generated)"
- `command`: `./bootstrap.sh --serve <repo_name>`
- `verified`: スモークテスト通過なら `true`
- `source`: `reports/webui/webui.json`
- `note`: ja「ブラウザから推論を実行できる。ポートは report 8000 / WebUI 7860 (ホスト側は bootstrap が自動割当・表示)」/ en 相当

**(3) `next_actions` に 1 エントリ追加** (generated: true のときのみ、priority=medium, effort=low, cost=free):

- `action`: ja「生成済みの推論 WebUI をブラウザで使う」/ en "Use the generated inference WebUI in a browser"
- `command`: `./bootstrap.sh --serve <repo_name>`

## ハルシネーション対策

| 対象 | 検証方法 |
|---|---|
| `command_template` の元コマンド | `attempts.tsv` の実在する success 行のみ。捏造 MUST NOT |
| `outputs[].glob` | Phase 3 の実出力ファイルに match するか `ls` / glob で確認 |
| `example_input` | `ls` で実在確認、無ければ `null` |
| 出力先引数の有無 | argparse 定義 / `_paper_default_args.json` を直接読む |

## 契約

生成・検証・report.json 用の値の返却のみ担当。サーバー起動 (Step 7) と HTML レンダリングは呼び出し元が行う。
