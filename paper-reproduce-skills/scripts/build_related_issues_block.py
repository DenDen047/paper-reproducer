#!/usr/bin/env python3
"""build_related_issues_block.py

search_github_issues.sh の出力 JSON を読み、report.html の
{{RELATED_ISSUES_BLOCK}} に流し込む HTML フラグメントを生成する。

results が空 (gh スキップ含む) の場合は empty メッセージを返す。
"""
import argparse
import html
import json
import sys
from pathlib import Path


def load_i18n(i18n_path: Path, lang: str) -> dict:
    with i18n_path.open() as f:
        d = json.load(f)
    if lang not in d:
        lang = "ja"
    return d[lang]


def render_empty(strings: dict) -> str:
    msg = html.escape(strings.get("empty_related_issues", "No related issues."))
    return f'<p class="usage-empty">{msg}</p>\n'


def render_results(results: list, strings: dict, max_items: int) -> str:
    if not results:
        return render_empty(strings)

    open_label = strings.get("related_issue_state_open", "open")
    closed_label = strings.get("related_issue_state_closed", "closed")
    matched_label = strings.get("related_issue_matched_label", "Matched query:")

    lines = ['<ul class="related-issues-list">']
    for item in results[:max_items]:
        kind = item.get("kind", "issue")
        number = item.get("number", "?")
        state = item.get("state", "")
        title = html.escape(item.get("title", ""))
        url = html.escape(item.get("url", ""))
        updated = html.escape((item.get("updated_at") or "")[:10])  # YYYY-MM-DD のみ
        matched_query = html.escape(item.get("matched_query", ""))
        kind_prefix = "PR" if kind == "pr" else "Issue"
        state_label = open_label if state == "open" else closed_label
        state_class = "open" if state == "open" else "closed"

        lines.append(
            "  <li>"
            f'<span class="ri-state ri-state-{state_class}">{html.escape(state_label)}</span> '
            f'<a href="{url}" target="_blank" rel="noopener">{kind_prefix} #{number}: {title}</a>'
            f'<span class="ri-meta"> &middot; {updated} &middot; '
            f'{html.escape(matched_label)} <code>{matched_query}</code></span>'
            "</li>"
        )
    lines.append("</ul>\n")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="search_github_issues.sh output JSON")
    parser.add_argument("--i18n", required=True, help="i18n.json path")
    parser.add_argument("--lang", default="ja")
    parser.add_argument("--max", type=int, default=10)
    parser.add_argument("--output", required=True, help="HTML fragment output path")
    args = parser.parse_args()

    strings = load_i18n(Path(args.i18n), args.lang)

    try:
        with open(args.input) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[build_related_issues_block] cannot read {args.input}: {e}", file=sys.stderr)
        data = {"results": []}

    results = data.get("results", []) if isinstance(data, dict) else []
    fragment = render_results(results, strings, args.max)
    Path(args.output).write_text(fragment, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
