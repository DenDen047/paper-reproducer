#!/usr/bin/env bash
# reports/report.html を HTTP 経由で開くためのローカルサーバ。
set -e
cd "$(dirname "${BASH_SOURCE[0]}")"
PORT="${PORT:-8000}"
echo "Open: http://localhost:${PORT}/report.html"
exec python3 -m http.server "$PORT"
