---
name: readme-writing
description: Use this skill when creating or updating a README file. Covers the funnel structure (What → Why → Install → How), keeping it concise, and separating concerns into dedicated files (CONTRIBUTING.md, CHANGELOG.md).
user-invocable: true
---

# README Writing: 読まれるREADMEの構造

> 出典: [MIT Missing Semester 2026 - Beyond the Code](https://missing.csail.mit.edu/2026/beyond-code/)

## 基本原則

**READMEはファネル（漏斗）構造で書く。** 上から順に読んで、必要な段階で離脱できるようにする。

## 4つの問い（この順序で答える）

### 1. What — これは何か？

1行で説明する。プロジェクト名を見ただけでは分からない人が最初に知りたいこと。

```markdown
# nanokit

Dotfile & development environment manager.
Declarative config with pixi-global and dotter.
```

可能なら視覚的なデモ（スクリーンショット、GIF、端末出力）を添える。

### 2. Why — なぜ気にすべきか？

ユーザーの課題を示し、このプロジェクトがどう解決するかを伝える。

```markdown
## Why?

- 新しいマシンのセットアップに毎回半日かかっていませんか？
- dotfileの管理がgit cloneとシンボリックリンクの手動作業になっていませんか？
- nanokitは1コマンドで開発環境を完全に再現します
```

詳細なドキュメントは別ファイル・別セクションに分ける。

### 3. Install — どうインストールするか？

Why の次に配置する。使うと決めた人がすぐインストールできるように。

```markdown
## Installation

\`\`\`bash
git clone https://github.com/user/nanokit.git
cd nanokit
./nanokit install
\`\`\`

Requirements: git, curl
```

### 4. How — どう使うか？

最も基本的な使い方を示す。Quick Start。

```markdown
## Usage

\`\`\`bash
./nanokit install        # Full setup
./nanokit claude-setup   # Claude Code config
./nanokit uninstall      # Remove everything
\`\`\`
```

## その他のセクション（必要に応じて追加）

| セクション | 対象読者 | README に入れるか |
|---|---|---|
| Contributing | 貢献者 | `CONTRIBUTING.md` に分離 |
| License | 法務・貢献者 | README にバッジ + 1行。詳細は `LICENSE` |
| Architecture | 開発者 | 別ドキュメント推奨 |
| FAQ | ユーザー | 量が多ければ別ファイル |
| Changelog | ユーザー | `CHANGELOG.md` に分離 |

## アンチパターン

- **全部入りREADME**: アーキテクチャ、API仕様、デプロイ手順...全てを1ファイルに
- **インストール先頭型**: What/Why より前にインストール手順を置く
- **更新されないREADME**: コードは変わったが README は初版のまま
