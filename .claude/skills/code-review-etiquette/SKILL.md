---
name: code-review-etiquette
description: Use this skill when reviewing others' code, writing review comments, or responding to code review feedback. Covers actionable comments, question-over-demand style, blocking vs nit distinction, and acknowledging good choices.
user-invocable: false
---

# Code Review Etiquette: レビューの作法

> 出典: [MIT Missing Semester 2026 - Beyond the Code](https://missing.csail.mit.edu/2026/beyond-code/)

## レビューコメントの書き方

### 1. アクショナブルなコメントを書く

```
# Bad
グローバル変数を使わないで

# Good
このグローバル変数を Config dataclass に置き換えられませんか？
そうすればテストを並列実行できるようになります。
```

「何がダメか」だけでなく「代わりにどうするか」と「なぜそうすべきか」を含める。

### 2. 命令ではなく質問で書く

```
# Bad
null ケースをハンドルしろ

# Good
ここに null が渡された場合、どうなりますか？
```

同じ内容でも、質問形は対話を促し、命令形は防御的な反応を引き起こす。著者が意図的にその設計を選んだ場合、質問形なら理由を説明してもらえる。

### 3. 理由（Why）を説明する

```
# Bad
この定数はハードコードしないで

# Good
この値を環境変数にすると、ステージング環境と本番環境で
異なるタイムアウトを使い分けられます。
```

指摘の背景にある動機を共有する。レビュイーにはその文脈がない場合が多い。

### 4. blocking と nit を区別する

- **blocking**: これが修正されないとマージできない
- **nit**: 好みの問題、改善提案。修正しなくても可

```
nit: 変数名は users_count より user_count が慣例に合います

blocking: この SQL クエリはユーザー入力を直接埋め込んでおり、
SQL インジェクションの脆弱性があります。プレースホルダーを使ってください。
```

`nit:` プレフィックスを使うことで、レビュイーがトリアージ（優先順位付け）できる。

### 5. 良い点も指摘する

```
このエラーハンドリングのアプローチ、とてもきれいですね。
再利用しやすい形になっていて参考になります。
```

レビューコメントが指摘ばかりだとバランスが悪い。良い設計判断も明示する。

### 6. コメントの量を制御する

- 同じパターンの繰り返しは1箇所だけ指摘し「他の箇所も同様にお願いします」と書く
- 100件コメントしても、半分は最初の50件を修正すれば無効になる
- 量が多いと重要な指摘が埋もれる
