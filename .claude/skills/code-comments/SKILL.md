---
name: code-comments
description: Use this skill when writing or modifying code that involves non-obvious logic, design trade-offs, or hard-learned lessons. Covers the 7 types of valuable comments (TODO, references, correctness arguments, hard-learned lessons, constant rationale, load-bearing choices, why-nots) and the principle of writing "why" not "what".
user-invocable: true
---

# Code Comments: 「Why」を書く技術

> 出典: [MIT Missing Semester 2026 - Beyond the Code](https://missing.csail.mit.edu/2026/beyond-code/)

## 基本原則

**コメントは「Why」を書く。「What」は書かない。**

コードそのものが「What（何をしているか）」を語る。コメントの役割は、コードからは読み取れない文脈を伝えること。

### 最も無駄なコメント

```python
# Bad: コードをそのまま繰り返している
i += 1  # increment i
```

### 価値あるコメント

```python
# Good: なぜこの実装を選んだかを説明
i += 1  # 0-indexed API response を 1-indexed UI 表示に変換
```

## 書くべきコメントの7類型

### 1. TODO — 具体的で文脈のあるもの

```python
# Bad
# TODO: fix this

# Good
# TODO: このO(n^2)ループはデータが10万件を超えるとタイムアウトする。
#       インデックスを使ったO(n log n)の実装に置き換える必要あり。
```

### 2. 参照 — アルゴリズムや外部ソースへのリンク

```python
# Knuth's Algorithm X を使用 (The Art of Computer Programming, Vol. 4, Fascicle 5)
# 参考実装: https://example.com/permalink (2026-01-15 閲覧)
# 注: 元実装から再帰→反復に変更（スタックオーバーフロー対策）
```

パーマリンクを使い、元の実装からの乖離があれば明記する。

### 3. 正当性の根拠 — なぜこのコードが正しく動くか

```python
# ここで配列が空でないことは保証されている:
# validate_input() が空配列の場合に ValueError を投げるため。
```

非自明なコードが正しい理由を説明する。特にエッジケースの処理で有用。

### 4. 苦労して得た教訓 — デバッグの成果

```python
# 注意: ここで time.sleep(0.1) を入れないと、
# macOS の FSEvents が変更を検知できないことがある。
# 2時間のデバッグの末に発見。Apple のバグレポート #FB12345 参照。
```

長時間のデバッグで得た知見は必ず残す。将来の開発者が同じ罠にはまるのを防ぐ。

### 5. 定数の根拠 — マジックナンバーの説明

```python
# Bad
TIMEOUT = 30

# Good
TIMEOUT = 30  # 99パーセンタイルのAPIレスポンスタイム(25s) + マージン5s
               # 2026-03 の本番メトリクスから導出
```

定数の由来を明記する: 任意に選んだのか、計測結果か、外部仕様か。

### 6. 耐荷重な選択 — 正確性に影響する実装詳細

```python
# OrderedDict を使用しているのは意図的。
# 挿入順序がシリアライズ出力の順序に影響し、
# 下流の差分比較ツールが順序に依存しているため。
```

「これは変えてはいけない」と伝える。変更すると壊れる理由を添える。

### 7. Why Not — なぜ明らかなアプローチを採用しなかったか

```python
# 標準ライブラリの json.dumps() を使わない理由:
# NaN を含む float のシリアライズで IEEE 754 非準拠の出力になり、
# Go 側のパーサーがエラーになる。orjson を使って回避。
```

**最も見落とされがちで、最も価値が高い。** 将来の開発者が「もっと簡単な方法があるのに」と書き直し、同じ問題を踏むのを防ぐ。

## アンチパターン

- **What コメント**: コードをそのまま自然言語に翻訳したもの
- **古くなったコメント**: コードは更新されたがコメントが残っている → 嘘のコメントは無いコメントより害がある
- **過剰なコメント**: すべての行にコメントを付ける → 読者の時間を奪い、本当に重要なコメントが埋もれる

## 量のバランス

- コメントが多すぎると重要なコメントが埋もれる
- 判断基準: 6ヶ月後にこのコードを見たとき、何を知る必要があるか
