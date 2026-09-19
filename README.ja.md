# paper-reproducer

<p align="center">
  <img src="docs/logo.png" alt="paper-reproducer logo" width="720">
</p>

💡 *CV論文リポジトリを、Pixiで固定された実行環境・リトライログ・監査しやすいレポートに変換するツール。*

<p align="center">
  <a href="README.md">English</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#出力例">出力例</a> ·
  <a href="#ossと商用機能の境界">商用境界</a>
</p>

<p align="center">
  <a href="https://opensource.org/licenses/Apache-2.0"><img alt="License: Apache 2.0" src="https://img.shields.io/badge/License-Apache_2.0-blue.svg"></a>
  <a href="https://www.claude.com/product/claude-code"><img alt="Claude Code plugin" src="https://img.shields.io/badge/Claude_Code-plugin-orange"></a>
  <a href="https://pixi.sh/"><img alt="Pixi powered" src="https://img.shields.io/badge/Pixi-powered-yellow"></a>
  <img alt="Status: early OSS" src="https://img.shields.io/badge/status-early_OSS-2ea44f">
</p>

`paper-reproducer` は、Claude Code または Codex CLI を使って GitHub上のCV論文リポジトリを再現するツールです。対象リポジトリをcloneし、依存ファイルを解析し、Pixi環境へ変換し、実行可能な推論・デモ経路を走らせ、失敗時は診断しながらリトライし、最後に再現レポートを出力します。

狙っているのは、AIコンサル・受託開発・応用研究で毎回重くなる「この論文コードは動くのか」「どこで詰まるのか」「顧客やチームに渡せる根拠は何か」を短時間で見える化することです。

## Demo

<!-- デモ動画用の予約枠です。想定フロー: ./bootstrap.sh <repo> -> /reimplement -> report.html -->

## なぜ作るのか

論文コードの再現は、アルゴリズムそのものよりも運用上の細かい問題で止まりがちです。

- 古い `conda` 環境、曖昧な `requirements.txt`、Docker前提の構成、依存ファイルなしのリポジトリ
- CUDA、PyTorch、compiler、system package のバージョン不整合
- README、Issue、スクリプトに散らばった重み・データセット・実行コマンド
- 失敗した試行がログとして残らず、次の人が同じ調査を繰り返す問題

`paper-reproducer` は、この作業を Pixi、Docker、構造化された記録で標準化し、各試行を確認・再実行・引き継ぎしやすくします。

## 何をするか

1. **cloneして解析**: 対象GitHubリポジトリのREADME、依存ファイル、スクリプトを確認します。
2. **依存管理方式を分類**: conda、pip、pyproject、setup files、Dockerfile、import解析に分けます。
3. **Pixi環境を構築**: Python、CUDA、compiler、packageを宣言的に固定します。
4. **推論・デモを実行**: リポジトリに実行可能な経路があれば走らせます。
5. **診断しながらリトライ**: 最初の環境構築失敗で止めず、原因を分類して次の手を試します。
6. **レポートを生成**: 人間向けHTML、機械可読JSON、試行ログ、サンプルを残します。

## Quick Start

前提ツール:

- Docker
- Claude Code または Codex のアカウント（選択した CLI だけを Docker イメージに同梱）
- Python 3
- GPUを使う場合は NVIDIA Container Toolkit
- バッチモードでは `tmux` と `flock`

```bash
$ git clone https://github.com/DenDen047/paper-reproducer.git
$ cd paper-reproducer
$ ./bootstrap.sh https://github.com/some-user/some-paper.git
```

Claude Code がコンテナ内で起動したら、次を実行します。

```text
/reimplement
```

英語レポートを出したい場合は `--lang en` を付けます。

```bash
$ ./bootstrap.sh --lang en https://github.com/some-user/some-paper.git
```

### Codex を使う

`--agent codex` で切り替えます。

```bash
./bootstrap.sh --agent codex https://github.com/some-user/some-paper.git
```

コンテナ内で Codex が起動したら、次を実行します。

```text
$paper-reproduce:reimplement
```

Claude Code と同じスキル・スキーマ・レポートテンプレートを使います。イメージは `paper-reproduce-codex` と `paper-reproduce-claude` に分かれ、選択した CLI だけを含みます。`IMAGE_NAME` で名前を指定した場合も、別エージェント用なら自動で再ビルドされます。既定は Claude Code で、`--agent claude` でも明示できます。

ホストの `${CODEX_HOME:-~/.codex}` を読み書き可能な状態でマウントし、設定・ログイン情報・更新されたトークンを引き継ぎます。モデルと reasoning effort は `config.toml` の設定に従います。コンテナ内ではファイル形式の認証情報を使うため、ホストのログインが OS のキーチェーンに保存されている場合は、先に次を実行してください。

```bash
codex -c 'cli_auth_credentials_store="file"' login
# API キーで認証する場合は標準入力から渡す:
printenv OPENAI_API_KEY | codex -c 'cli_auth_credentials_store="file"' login --with-api-key
```

ログイン情報が無い場合は、コンテナ内で **Sign in with Device Code** を選択できます（[Codex の認証手順](https://learn.chatgpt.com/docs/auth#login-on-headless-devices)）。コンテナ用の設定を分ける場合は `CODEX_HOME` に別ディレクトリを指定してください。選択した設定にホスト固有の MCP コマンド・フック・絶対パスがある場合、Linux コンテナ内でも使える必要があります。マウントする設定ディレクトリは選択した CLI のものだけです。

両 CLI とも内部の承認プロンプトを無効にし、Docker を実行境界として動作します。マウント先は書き込み可能です。Codex 用スキルは公式の[スキル検出パス](https://learn.chatgpt.com/docs/build-skills#where-to-save-skills)である `/etc/codex/skills` から読み込みます。

## 出力例

各実行では、再現対象リポジトリ配下に監査しやすい記録が残ります。

| パス | 内容 |
|---|---|
| `reports/analysis.json` | リポジトリ解析、依存分類、実行可否の見立て |
| `reports/attempts.tsv` | 全試行のaction、result、error tier、duration |
| `reports/environment.json` | host、OS、CPU、GPU、CUDA、Python のスナップショット |
| `reports/report.json` | 機械可読な再現結果 |
| `reports/report.html` | 人間が確認しやすい再現レポート |
| `reports/samples/` | 再現中に得られた入出力サンプル |
| `{repo}-{short_sha}.tar.gz` | 成功時の状態スナップショット |

重要なのは「動いたかどうか」だけではありません。何を試し、何が通り、何で失敗し、次に何をすべきかが残ることです。

## 仕組み

```mermaid
flowchart TD
    Start([/reimplement]) --> Read["読む<br/>README, dependency files, scripts, demos"]
    Read --> Classify["分類<br/>A-F dependency type<br/>conda / pip / pyproject / Docker / setup / source"]
    Classify --> Gate{"このマシンで実行可能?<br/>GPU / disk / data / auth"}
    Gate -- 不可 --> Fail["ブロッカーをレポート<br/>理由 + 代替案"]
    Gate -- 可 --> Build["環境構築<br/>Pixi env + lockfile<br/>解決できるまでリトライ"]
    Build --> Run["実行<br/>weights取得<br/>inference/demo実行<br/>OOM時は可能なら調整"]
    Run --> Report["レポート<br/>HTML + JSON + attempts.tsv + samples"]
```

## 対応する依存管理タイプ

対象リポジトリ内で見つかったファイルに応じて、Pixiへの変換戦略を選びます。

| 優先度 | Type | 依存ファイル | 戦略 |
|---:|---|---|---|
| 1 | A | `environment.yml`, `conda.yaml` | `pixi init --import` + divide-and-conquer |
| 2 | C | `pyproject.toml` | `pixi init --pyproject` |
| 3 | B | `requirements.txt` | `pixi init` + PyPI依存変換 |
| 4 | E | `setup.py`, `setup.cfg` | 依存抽出してPixiへ変換 |
| 5 | D | `Dockerfile` のみ | image、apt、pip、CUDAを解析してA/B戦略へ合流 |
| 6 | F | 依存ファイルなし | import解析とソースマイニング |

## バッチモード

複数URL、またはURL一覧ファイルを渡すと、`tmux` で並列実行します。

```bash
./bootstrap.sh url1.git url2.git url3.git
./bootstrap.sh --repos repos.txt
./bootstrap.sh --agent codex --repos repos.txt
```

GPU環境では、空いているGPUを `--gpus device=N` で割り当て、`flock` により1つのGPUスロットを1ジョブだけが使うようにします。

各ウィンドウは対話式です。Claude Code では `/reimplement`、Codex では `$paper-reproduce:reimplement` を入力してください。

## ライセンスゲート資産 (SMPL, SMAL, ...)

一部のCV論文は、Max Planck Institute（Michael Black ラボ）製のパラメトリックモデル — SMPL / SMPL-X / SMPL+H / MANO / FLAME / STAR / SMAL — に依存します。これらは各モデルのライセンス同意が必須で、**自動ダウンロードできません**（HuggingFace のようなトークン取得も不可）。

`paper-reproducer` はこれらをダウンロード・同梱・ミラー・再配布しません。**一度だけ手作業で**用意します:

1. 必要なモデルを各サイトで登録・DL（取得元と配置レイアウトは [`paper-reproduce-skills/registry/ASSETS.md`](paper-reproduce-skills/registry/ASSETS.md)）。
2. リポジトリ直下の `manual-assets/`（`.gitignore` 済み、`MANUAL_ASSETS_DIR` で変更可）に配置。
3. いつも通り `./bootstrap.sh <repo>` を実行 — `/reimplement` が repo の必要モデルを検出し、適切なパスへ自動コピーします。配置物は `.gitignore` 済みで成功アーカイブにも入りません。

状態確認は `./bootstrap.sh --list-assets`。未配置でも処理は止まらず、何をどこへ DL すべきかをレポートに記録します。これらのモデルの利用は非商用研究ライセンスに従い、遵守は利用者の責任です。

## CLI Reference

<!-- AUTO-GENERATED: bootstrap.sh usage() is the source of truth -->

| オプション | 役割 |
|---|---|
| `--agent <name>` | 使用する CLI。`claude`（既定）または `codex` |
| `--repos <file>` | URLをファイルから読み込む |
| `--rebuild` | Docker image を強制再ビルド |
| `--fresh` | 既存cloneを削除して再clone |
| `--full` | 学習と claim の定量検証まで実行（両エージェント共通） |
| `--lang <code>` | レポート言語: `ja` または `en` |
| `--list-assets` | 手動資産レジストリ（ライセンスゲートモデル）の状態を表示して終了 |
| `-h`, `--help` | ヘルプ表示 |

| 環境変数 | 役割 |
|---|---|
| `PAPER_REPRODUCER_AGENT` | 既定の CLI。`--agent` が優先 |
| `IMAGE_NAME` | Docker イメージ名。既定は `paper-reproduce-<agent>` |
| `CODEX_HOME` | ホストの Codex 設定・認証ディレクトリ。既定は `~/.codex` |
| `WORKSPACE_DIR` | clone先。デフォルトは `~/paper-reproduce-workspaces` |
| `MANUAL_ASSETS_DIR` | ライセンスゲート資産(SMPL/SMAL 等)の置き場。デフォルトは `./manual-assets`(gitignore 済み) |
| `REPORT_LANG` | `--lang` と同じ。`--lang` が優先 |

<!-- /AUTO-GENERATED -->

## 制約

- 現時点では、CV論文リポジトリ向けに最適化しています。
- gated dataset、private model weights、上流ライセンス制約は回避しません。
- 論文中の主張を完全に再現できたことまでは保証しません。利用可能な再現経路とブロッカーを記録します。
- GPU負荷が大きい論文は、ローカルマシンでは実行不能な場合があります。
- 再現対象リポジトリや取得したassetは、それぞれの元ライセンスに従います。

## Roadmap

- READMEに短いデモ動画を追加する
- CV論文の再現case studyを公開する
- コンサル・調達向けの監査パックを強化する
- 未信頼の論文コードを実行するための安全ポリシーを強化する
- 社内で再現レシピを保持したいチーム向けにCI引き継ぎテンプレートを追加する
- private dashboard と商用サポートパッケージを検討する

## OSSと商用機能の境界

`paper-reproducer` 本体は Apache-2.0 ライセンスで公開しています。

このツールは第三者の論文リポジトリを取得・変更・実行しますが、それらの対象リポジトリを本プロジェクトのライセンスに変更するものではありません。対象リポジトリ、データセット、モデル重みは、それぞれの元ライセンス・利用規約に従います。

商用化する場合は、OSS本体の上に載る運用層を想定しています。private support、audit-pack生成、安全な実行profile、reporting dashboard、チーム固有のintegrationなどです。

## Development

- `main` ブランチをベースに開発します。
- 大きめの変更は `feature/<name>` ブランチで進めます。
- コミットメッセージは [Conventional Commits](https://www.conventionalcommits.org/ja/v1.0.0/) に従います。
- バージョニングは [Semantic Versioning 2.0.0](https://semver.org/lang/ja/) に従います。
- リリースノートは [CHANGELOG.md](./CHANGELOG.md) を参照してください。
- テストは `pytest -q tests/` で実行します（導入は `pixi global install pytest`）。起動テストでは CLI を置き換えるため Docker・GPU・認証情報は不要です。`CODEX_BINARY=codex pytest -q tests/` では実際の Codex によるスキル検出も確認します。CI ではこれらに加え、各イメージで選択した CLI の起動と、もう一方の CLI が入っていないことを確認します。

## References

- [Pixi](https://pixi.sh/)
- [Claude Code](https://www.claude.com/product/claude-code)
- [Codex CLI](https://learn.chatgpt.com/docs/cli)
- [karpathy/autoresearch](https://github.com/karpathy/autoresearch)
- [denkiwakame - Pixi Advent Calendar 2024](https://denkiwakame.notion.site/2ba3175c6b6a80d19141f5407c39ad4e?v=2ba3175c6b6a80a7acfe000c6c1b2117)
