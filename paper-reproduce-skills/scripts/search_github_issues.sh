#!/usr/bin/env bash
# search_github_issues.sh
# Phase 3 / Phase 4 共用の gh search ラッパ。
# 失敗 (gh 未インストール / 未認証 / rate-limit / 4xx-5xx) しても再現フローをブロックしない。
# 必ず exit 0 で valid JSON を出力する。

set -u

usage() {
  cat <<'EOF' >&2
Usage:
  search_github_issues.sh --repo OWNER/REPO --output PATH
                          [--query "term" ...] [--limit N] [--kind issues|prs|both]

  --repo OWNER/REPO    : 検索対象リポジトリ (必須)
  --output PATH        : JSON 出力先 (必須)
  --query "term"       : 検索クエリ (複数指定可、各 query を独立に呼ぶ)
  --limit N            : query あたり最大取得件数 (default: 5)
                         Phase 4 の集約検索で 8 query × 5 件 = 上限 40 件まで増えるが、
                         dedupe 後に上位 10 件のみレポートに出すので 5 で十分
  --kind KIND          : issues | prs | both (default: issues)

出力 JSON (常に valid):
  {
    "repo": "...",
    "skipped": "gh-unavailable" | "no-auth" | null,
    "results": [
      {"number": N, "title": "...", "url": "...", "state": "open|closed",
       "updated_at": "...", "kind": "issue|pr",
       "matched_query": "...", "body_excerpt": "..."}
    ]
  }
EOF
  exit 2
}

REPO=""
OUTPUT=""
# 1 query あたり 5 件は: open + closed の両方を拾うのに十分な小数で、かつ
# 1 query につき 1 リクエスト + 軽い JSON パースで済む規模 (rate limit を圧迫しない)
LIMIT=5
KIND="issues"
QUERIES=()

while [ $# -gt 0 ]; do
  case "$1" in
    --repo)   REPO="${2:-}"; shift 2 ;;
    --output) OUTPUT="${2:-}"; shift 2 ;;
    --limit)  LIMIT="${2:-5}"; shift 2 ;;
    --kind)   KIND="${2:-issues}"; shift 2 ;;
    --query)  QUERIES+=("${2:-}"); shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown arg: $1" >&2; usage ;;
  esac
done

[ -z "$REPO" ] && usage
[ -z "$OUTPUT" ] && usage

write_empty() {
  local reason="$1"
  python3 - "$REPO" "$reason" "$OUTPUT" <<'PY'
import json, sys
repo, reason, out = sys.argv[1], sys.argv[2], sys.argv[3]
payload = {"repo": repo, "skipped": reason or None, "results": []}
with open(out, "w") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
PY
}

# gh 未インストール → スキップ (exit 0)
if ! command -v gh >/dev/null 2>&1; then
  echo "[search_github_issues] gh not installed; skipping" >&2
  write_empty "gh-unavailable"
  exit 0
fi

# gh 未認証 → スキップ
if ! gh auth status >/dev/null 2>&1; then
  echo "[search_github_issues] gh not authenticated; skipping" >&2
  write_empty "no-auth"
  exit 0
fi

# クエリ無し → 空 results を返して終了 (エラーではない)
if [ "${#QUERIES[@]}" -eq 0 ]; then
  write_empty ""
  exit 0
fi

# kind を gh search コマンド名に
case "$KIND" in
  issues) GH_CMDS=("issues") ;;
  prs)    GH_CMDS=("prs") ;;
  both)   GH_CMDS=("issues" "prs") ;;
  *) echo "Invalid --kind: $KIND" >&2; write_empty "bad-kind"; exit 0 ;;
esac

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

INDEX=0
for query in "${QUERIES[@]}"; do
  for cmd in "${GH_CMDS[@]}"; do
    INDEX=$((INDEX + 1))
    OUT_FILE="$TMP_DIR/r_${INDEX}.json"
    # gh search は body フィールドを返さない仕様の版もあるため json fields を限定。
    # 失敗しても再現フローを止めない: stderr に流して空 [] を入れる。
    if ! gh search "$cmd" \
          --repo "$REPO" \
          --json "url,title,state,updatedAt,number" \
          --limit "$LIMIT" \
          -- "$query" \
          > "$OUT_FILE" 2>/dev/null; then
      echo "[search_github_issues] gh search $cmd failed (query=\"$query\"); continuing" >&2
      echo "[]" > "$OUT_FILE"
    fi
    # kind / matched_query をマージ用に各エントリに付与
    python3 - "$OUT_FILE" "$cmd" "$query" <<'PY'
import json, sys
path, kind, query = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(path) as f:
        data = json.load(f)
except Exception:
    data = []
if not isinstance(data, list):
    data = []
kind_singular = "pr" if kind == "prs" else "issue"
for item in data:
    item["kind"] = kind_singular
    item["matched_query"] = query
with open(path, "w") as f:
    json.dump(data, f, ensure_ascii=False)
PY
  done
done

# マージ + dedupe (number+kind がキー) + 整形
python3 - "$REPO" "$OUTPUT" "$TMP_DIR" <<'PY'
import glob, json, os, sys

repo, out, tmp = sys.argv[1], sys.argv[2], sys.argv[3]

merged = {}
for path in sorted(glob.glob(os.path.join(tmp, "r_*.json"))):
    try:
        with open(path) as f:
            entries = json.load(f)
    except Exception:
        continue
    for item in entries:
        number = item.get("number")
        kind = item.get("kind", "issue")
        if number is None:
            continue
        key = (kind, number)
        if key in merged:
            # 既存より新しい matched_query を優先 (検索順がスコア順なので最初を残す)
            continue
        merged[key] = {
            "number": number,
            "kind": kind,
            "title": item.get("title") or "",
            "url": item.get("url") or "",
            "state": (item.get("state") or "").lower(),
            "updated_at": item.get("updatedAt") or item.get("updated_at") or "",
            "matched_query": item.get("matched_query") or "",
            "body_excerpt": "",
        }

# state が open のものを先頭、その中で updated_at の新しい順
def sort_key(it):
    state_pri = 0 if it["state"] == "open" else 1
    return (state_pri, -(len(it["updated_at"])), it["updated_at"])

results = sorted(merged.values(), key=sort_key, reverse=False)
# updated_at で降順にしたいので二段階ソート
results = sorted(merged.values(), key=lambda it: it["updated_at"], reverse=True)
results = sorted(results, key=lambda it: 0 if it["state"] == "open" else 1)

payload = {"repo": repo, "skipped": None, "results": results}
with open(out, "w") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
PY

exit 0
