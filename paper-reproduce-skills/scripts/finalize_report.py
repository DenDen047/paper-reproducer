#!/usr/bin/env python3
"""finalize_report.py

reports/report.html の最終ゲート。Phase 4 Step 3 の i18n 置換で取りこぼされた
{{...}} を以下の順で処理し、ユーザーがメタコードを目にしないことを保証する。

  1. {{#FLAG}}...{{/FLAG}} の Mustache 風条件ブロックを開閉処理
     - flags 引数で True と指定されたタグは開閉タグだけ削除して中身を残す
     - False / 未指定のタグはブロックごと削除
  2. 残った {{T_FOO_BAR}} を i18n.json[lang]["foo_bar"] から再 lookup して置換
  3. {{I18N_JSON_INLINE}} は dict 全体を JSON 化して埋め込む (なければ "{}")
  4. それでも残った {{...}} は種別ごとに非表示化:
     - <h2>{{T_H2_*}}</h2> ... 次の <h2>/<div class="footer">/<script> 直前まで削除
     - <h3>{{T_H3_*}}</h3> ... <h3> 行のみ削除 (中身は他の placeholder で守られる)
     - <dt>...</dt><dd>{{T_LEGEND_*_DESC}}</dd> ... その <dt><dd> ペアを削除
     - {{*_BLOCK}} ... <p class="usage-empty"> でフォールバック
     - その他 ... 空文字に置換 (warning ログ)
"""
import argparse
import json
import re
import sys
from pathlib import Path


PLACEHOLDER_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
MUSTACHE_BLOCK_RE = re.compile(
    r"\{\{#([A-Z][A-Z0-9_]*)\}\}(.*?)\{\{/\1\}\}",
    re.DOTALL,
)


def load_i18n(i18n_path: Path, lang: str) -> dict:
    with i18n_path.open() as f:
        d = json.load(f)
    if lang not in d:
        lang = "ja"
    return d[lang]


def process_mustache_blocks(html: str, flags: dict) -> str:
    def repl(m: re.Match) -> str:
        name = m.group(1)
        body = m.group(2)
        if flags.get(name, False):
            return body
        return ""
    # ネストは想定しない (テンプレに無い)
    return MUSTACHE_BLOCK_RE.sub(repl, html)


def lookup_i18n(token: str, strings: dict) -> str | None:
    """{{T_FOO_BAR}} -> strings["foo_bar"]"""
    if not token.startswith("T_"):
        return None
    key = token[2:].lower()
    return strings.get(key)


def reapply_i18n(html: str, strings: dict) -> str:
    def repl(m: re.Match) -> str:
        token = m.group(1)
        value = lookup_i18n(token, strings)
        if value is None:
            return m.group(0)  # 未解決のまま残し、後段で hide
        # T_ 系は inline 文字列なので minimal escape (i18n.json 自体に HTML が含まれることを許容)
        return value
    return PLACEHOLDER_RE.sub(repl, html)


def fill_i18n_inline(html: str, strings: dict) -> str:
    if "{{I18N_JSON_INLINE}}" not in html:
        return html
    payload = json.dumps(strings, ensure_ascii=False)
    # JS インライン埋め込み時の最小エスケープ (CSP 等は範囲外)
    payload = payload.replace("</", "<\\/")
    return html.replace("{{I18N_JSON_INLINE}}", payload)


# H2 ブロックの境界。<h2>{{T_H2_FOO}}</h2> から、次の終端マーカー直前まで。
H2_HIDE_RE = re.compile(
    r"<!--\s*=+\s*[^=]*=+\s*-->\s*"
    r"<h2>\{\{T_H2_[A-Z0-9_]+\}\}</h2>"
    r".*?"
    r"(?=<!--\s*=+|<h2>|<div class=\"footer\">|<script)",
    re.DOTALL,
)
# 上のフォールバック (コメント無し H2 の場合)
H2_HIDE_NOCOMMENT_RE = re.compile(
    r"<h2>\{\{T_H2_[A-Z0-9_]+\}\}</h2>"
    r".*?"
    r"(?=<!--\s*=+|<h2>|<div class=\"footer\">|<script)",
    re.DOTALL,
)
H3_HIDE_RE = re.compile(r"\s*<h3>\{\{T_H3_[A-Z0-9_]+\}\}</h3>\s*\n")
LEGEND_DT_HIDE_RE = re.compile(
    r"\s*<dt>[^<]*</dt><dd>\{\{T_LEGEND_[A-Z0-9_]+\}\}</dd>\s*\n"
)


def hide_unresolved_sections(html: str, warnings: list) -> str:
    # H2 セクションごと削除 (コメント headed の方を優先)
    def hide_h2(m: re.Match) -> str:
        warnings.append(f"hidden H2 section: {m.group(0)[:80]}...")
        return ""
    html = H2_HIDE_RE.sub(hide_h2, html)
    html = H2_HIDE_NOCOMMENT_RE.sub(hide_h2, html)

    # H3 行のみ削除
    def hide_h3(m: re.Match) -> str:
        warnings.append(f"hidden H3: {m.group(0).strip()}")
        return ""
    html = H3_HIDE_RE.sub(hide_h3, html)

    # legend dt/dd ペア
    def hide_dt(m: re.Match) -> str:
        warnings.append(f"hidden legend row: {m.group(0).strip()}")
        return ""
    html = LEGEND_DT_HIDE_RE.sub(hide_dt, html)

    # 残った {{...}} は最後のフォールバック
    def fallback(m: re.Match) -> str:
        token = m.group(1)
        warnings.append(f"unresolved placeholder removed: {{{{ {token} }}}}")
        if token.endswith("_BLOCK"):
            return '<p class="usage-empty">—</p>'
        return ""
    html = PLACEHOLDER_RE.sub(fallback, html)
    return html


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="report.html (in-place 上書き)")
    parser.add_argument("--i18n", required=True, help="templates/i18n.json")
    parser.add_argument("--lang", default="ja")
    parser.add_argument(
        "--flag",
        action="append",
        default=[],
        help="Mustache-style flag, e.g. --flag ERRORS --flag RELATED_ISSUES",
    )
    args = parser.parse_args()

    flags = {name: True for name in args.flag}
    strings = load_i18n(Path(args.i18n), args.lang)

    path = Path(args.input)
    html = path.read_text(encoding="utf-8")

    # Step 1: Mustache 条件ブロック
    html = process_mustache_blocks(html, flags)

    # Step 2: i18n 再 lookup
    html = reapply_i18n(html, strings)

    # Step 3: I18N_JSON_INLINE
    html = fill_i18n_inline(html, strings)

    # Step 4: 残ったものを種別ごとに非表示
    warnings: list[str] = []
    html = hide_unresolved_sections(html, warnings)

    # 最終確認
    leftover = PLACEHOLDER_RE.findall(html)
    mustache_leftover = MUSTACHE_BLOCK_RE.findall(html)
    if leftover or mustache_leftover:
        warnings.append(
            f"FATAL: still unresolved after hide step: placeholders={leftover}, "
            f"mustache={[t[0] for t in mustache_leftover]}"
        )

    path.write_text(html, encoding="utf-8")

    for w in warnings:
        print(f"[finalize_report] {w}", file=sys.stderr)
    # 設計上 exit 0 (ユーザー指示: 「該当セクションを非表示」最優先で再現フローを止めない)
    return 0


if __name__ == "__main__":
    sys.exit(main())
