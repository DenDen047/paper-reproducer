---
name: git-commits
description: Use this skill when creating git commits, splitting large changes into multiple commits, or writing commit messages. Covers commit granularity (one logical change per commit) and message structure (Problem → Solution → Implications).
user-invocable: true
---

# Git Commits: 粒度とメッセージ

> 出典: [MIT Missing Semester 2026 - Beyond the Code](https://missing.csail.mit.edu/2026/beyond-code/)

## コミット粒度

### 原則: 1コミット = 1つの論理的変更

- 各コミットは独立してレビュー可能で、単体で意味を持つべき
- リファクタリング・機能追加・バグ修正・フォーマット変更を混ぜない
- 巨大な diff は意味のある単位に分割する

### なぜ粒度が重要か

- **デバッグ効率**: バグを導入したコミットを二分探索 (`git bisect` など) で特定できる。コミットが巨大だと特定しても原因箇所が絞れない
- **レビュー効率**: レビュアーは小さく焦点の絞れた変更を好む。無関係な変更が混ざると却下される
- **歴史の可読性**: `git log` / `git blame` で「なぜこの行が変わったか」を追跡できる
- **部分的な採用**: OSSでは一部の変更だけマージし、他は保留にできる

### 分割テクニック

- `git add -p` でハンク単位でステージングし、意味的に関連する変更だけをコミットする
- sub-agent に diff を渡して「意味的に独立した変更グループに分けて」と依頼するのも有効

## コミットメッセージ

### 構造

```
<type>: <subject>

<body>
```

- **type**: 変更の種類 (feat, fix, refactor, chore, docs, style, test)
- **subject**: 変更の要約（命令形、50文字以内目安）
- **body**: 詳細な文脈（72文字折り返し目安）

### body に書くべき4つの問い

1. **何がこの変更を強制したか？** — 問題・要件・制約の説明
2. **どんな代替案を検討したか？** — なぜこの方法を選んだか
3. **トレードオフや影響は？** — 例: ランタイムは速くなるがビルド時間は増加
4. **驚くべき点は？** — 非自明な副作用や注意事項

### スケーリング

- 1行のtypo修正 → subject だけで十分
- 複雑な変更 → Problem → Solution → Implications の構造で body を書く

### アンチパターン

- `fix bug` / `update` / `misc changes` のような中身のないメッセージ
- diff の「何」をそのまま繰り返すだけのメッセージ（「Add function foo to bar.py」）
- 無関係な変更を1コミットにまとめる
