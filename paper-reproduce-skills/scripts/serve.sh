#!/usr/bin/env bash
# serve.sh — コンテナ内でレポート HTTP サーバ + 生成済み推論 WebUI を起動する。
#
# 呼び出し元は 2 つ:
#   1. /reimplement Phase 4 Step 7 (--no-wait): レポート生成直後に同一コンテナ内で
#      background 起動し、Claude Code セッション中はそのままアクセスできる
#   2. bootstrap.sh --serve (entrypoint.sh 経由、引数なし): Claude Code 抜きの
#      常設配信モード。フォアグラウンドで wait し、コンテナの main process になる
#
# ポートはコンテナ内固定 (report 8000 / webui 7860)。ホスト側の割当は
# bootstrap.sh が -p で行い、REPORT_HOST_PORT / WEBUI_HOST_PORT env で通知される
# (表示用。未設定ならコンテナ内ポートをそのまま表示)。
set -euo pipefail

REPORT_PORT_INTERNAL=8000
WEBUI_PORT_INTERNAL=7860

REPO_DIR="$PWD"
NO_WAIT=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-dir) REPO_DIR="$2"; shift 2 ;;
    --no-wait)  NO_WAIT=1; shift ;;
    *) echo "[serve] unknown option: $1" >&2; exit 2 ;;
  esac
done

log() { printf '[serve] %s\n' "$*" >&2; }

REPORTS_DIR="$REPO_DIR/reports"
[[ -d "$REPORTS_DIR" ]] || { log "error: $REPORTS_DIR not found (run /reimplement first)"; exit 1; }
[[ -f "$REPORTS_DIR/report.html" ]] || log "WARN: report.html not found yet (serving reports/ anyway)"

port_in_use() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

PIDS=()

# --- レポートサーバ (python3 -m http.server は既定で全インターフェース bind) ---
if port_in_use "$REPORT_PORT_INTERNAL"; then
  log "report server already running on :$REPORT_PORT_INTERNAL — skip"
else
  python3 -m http.server "$REPORT_PORT_INTERNAL" --directory "$REPORTS_DIR" \
    >/tmp/serve-report.log 2>&1 &
  PIDS+=($!)
  log "report server started on :$REPORT_PORT_INTERNAL (log: /tmp/serve-report.log)"
fi

# --- 推論 WebUI (生成済みのときだけ) ---
WEBUI_DIR="$REPORTS_DIR/webui"
if [[ -f "$WEBUI_DIR/webui.json" && -f "$WEBUI_DIR/app.py" ]]; then
  if port_in_use "$WEBUI_PORT_INTERNAL"; then
    log "webui already running on :$WEBUI_PORT_INTERNAL — skip"
  else
    # pixi run は env 未作成なら lock から自動インストールする
    (cd "$WEBUI_DIR" && exec pixi run python app.py --port "$WEBUI_PORT_INTERNAL") \
      >/tmp/serve-webui.log 2>&1 &
    PIDS+=($!)
    log "webui starting on :$WEBUI_PORT_INTERNAL (log: /tmp/serve-webui.log)"
  fi
else
  log "no generated webui (reports/webui/webui.json missing) — report server only"
fi

REPORT_HOST="${REPORT_HOST_PORT:-$REPORT_PORT_INTERNAL}"
WEBUI_HOST="${WEBUI_HOST_PORT:-$WEBUI_PORT_INTERNAL}"
log "report: http://localhost:${REPORT_HOST}/report.html"
[[ -f "$WEBUI_DIR/webui.json" ]] && log "webui:  http://localhost:${WEBUI_HOST}/"
log "(remote host? tunnel with: ssh -L ${WEBUI_HOST}:localhost:${WEBUI_HOST} -L ${REPORT_HOST}:localhost:${REPORT_HOST} <host>)"

if [[ "$NO_WAIT" == "1" ]]; then
  exit 0
fi

trap '[[ ${#PIDS[@]} -gt 0 ]] && kill "${PIDS[@]}" 2>/dev/null; exit 0' INT TERM
if [[ ${#PIDS[@]} -gt 0 ]]; then
  wait "${PIDS[@]}"
else
  log "nothing started here (both ports already in use) — nothing to wait for"
fi
