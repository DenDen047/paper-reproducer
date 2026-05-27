#!/usr/bin/env bash
# bootstrap.sh — paper-reproducer の起動スクリプト
#
# 1 個の GitHub URL を渡すと単一モード
# 2 個以上または --repos <file> を渡すと並列バッチモード
#
# 使い方:
#   # 単一モード (1 URL)
#   ./bootstrap.sh <github-url>
#
#   # 並列バッチモード (複数 URL)
#   ./bootstrap.sh <url1> <url2> <url3>
#
#   # 並列バッチモード (ファイルから URL を読み込み)
#   ./bootstrap.sh --repos repos.txt

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKERFILE_DIR="$SCRIPT_DIR/paper-reproduce-skills"
IMAGE_NAME="${IMAGE_NAME:-paper-reproduce}"
WORKSPACE_DIR="${WORKSPACE_DIR:-$HOME/paper-reproduce-workspaces}"
PIXI_CACHE_VOLUME="${PIXI_CACHE_VOLUME:-paper-reproduce-pixi-cache}"

REBUILD=0
FRESH=0
REPOS_FILE=""
URLS=()
REPORT_LANG="${REPORT_LANG:-ja}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [options] <github-url>...
       $(basename "$0") [options] --repos <file>

Run /reimplement on one or more repositories.
  1 URL   interactive
  2+ URLs parallel batch (GPUs round-robin)

Options:
  --repos <file>     Read URLs from file
  --rebuild          Force Docker image rebuild
  --fresh            Re-clone over existing clones
  --lang <code>      Report output language: ja (default) | en
  -h, --help         Show this help

Environment:
  WORKSPACE_DIR      Host clone dir (default: ~/paper-reproduce-workspaces)
  REPORT_LANG        Same as --lang (default: ja); overridden by --lang

Examples:
  ./bootstrap.sh https://github.com/user/repo.git
  ./bootstrap.sh url1.git url2.git url3.git
  ./bootstrap.sh --repos repos.txt
EOF
}

log() { printf '[bootstrap] %s\n' "$*" >&2; }
die() { printf '[bootstrap] error: %s\n' "$*" >&2; exit 1; }

# --- 引数のパース ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rebuild) REBUILD=1; shift ;;
    --fresh)   FRESH=1; shift ;;
    --repos)
      [[ $# -ge 2 ]] || die "--repos requires a file argument"
      REPOS_FILE="$2"; shift 2 ;;
    --repos=*)
      REPOS_FILE="${1#*=}"; shift ;;
    --lang)
      [[ $# -ge 2 ]] || die "--lang requires an argument (ja|en)"
      REPORT_LANG="$2"; shift 2 ;;
    --lang=*)
      REPORT_LANG="${1#*=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    --) shift; break ;;
    -*) die "unknown option: $1 (see --help)" ;;
    *) URLS+=("$1"); shift ;;
  esac
done
while [[ $# -gt 0 ]]; do
  URLS+=("$1"); shift
done

if [[ -n "$REPOS_FILE" ]]; then
  [[ -f "$REPOS_FILE" ]] || die "repos file not found: $REPOS_FILE"
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue
    URLS+=("$line")
  done < "$REPOS_FILE"
fi

if [[ ${#URLS[@]} -eq 0 ]]; then
  usage >&2
  exit 2
fi

case "$REPORT_LANG" in
  ja|en) ;;
  *) die "unsupported --lang '$REPORT_LANG' (expected: ja | en)" ;;
esac
log "report language: $REPORT_LANG"

# --- 事前チェック（共通）---
command -v git     >/dev/null 2>&1 || die "git not found on PATH"
command -v docker  >/dev/null 2>&1 || die "docker not found on PATH"
command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH (required for batch summary)"
[[ -f "$DOCKERFILE_DIR/Dockerfile" ]] || die "Dockerfile not found at $DOCKERFILE_DIR"

# --- Docker イメージのビルド（共通）---
# host UID/GID を build-arg で渡す。bind-mount した ~/.claude(.json) を
# コンテナ内の claude user が読めるようにするため。
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"
IMAGE_UID_LABEL=""
if docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
  IMAGE_UID_LABEL="$(docker image inspect "$IMAGE_NAME" \
    --format '{{ index .Config.Labels "host.uid" }}{{":"}}{{ index .Config.Labels "host.gid" }}' 2>/dev/null || true)"
fi
NEED_BUILD=0
if [[ "$REBUILD" == "1" ]]; then NEED_BUILD=1
elif ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then NEED_BUILD=1
elif [[ "$IMAGE_UID_LABEL" != "${HOST_UID}:${HOST_GID}" ]]; then
  log "image was built with UID/GID '$IMAGE_UID_LABEL', host is '${HOST_UID}:${HOST_GID}' — rebuilding"
  NEED_BUILD=1
fi
if [[ "$NEED_BUILD" == "1" ]]; then
  log "building image: $IMAGE_NAME (UID=$HOST_UID GID=$HOST_GID)"
  # CLAUDE_CODE_BUILD に日付を渡し、--rebuild した日が変われば install.sh の
  # layer cache が破棄され最新の Claude Code を取り直す (opus[1m] を扱える
  # ≥2.1.144 を確実に入れるため。Dockerfile 参照)。
  docker build \
    --build-arg "USER_UID=${HOST_UID}" \
    --build-arg "USER_GID=${HOST_GID}" \
    --build-arg "CLAUDE_CODE_BUILD=$(date +%Y%m%d)" \
    --label "host.uid=${HOST_UID}" \
    --label "host.gid=${HOST_GID}" \
    -t "$IMAGE_NAME" "$DOCKERFILE_DIR"
else
  log "image $IMAGE_NAME already present (use --rebuild to force)"
fi

# --- GPU 検出 + 枚数カウント ---
# 単一モードは GPU_FLAGS=(--gpus all) のまま使う。
# 並列バッチは外部プロセス未使用の GPU だけを選び、--gpus "device=N" + flock で
# 1 GPU 1 コンテナの排他を保証する (silent な CUDA OOM → CPU fallback を防ぐ)。
GPU_FLAGS=()
NUM_GPUS=0
FREE_GPUS=()
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  GPU_FLAGS=(--gpus all)
  # nvidia-smi -L の行数が GPU 枚数
  NUM_GPUS=$(nvidia-smi -L 2>/dev/null | grep -c '^GPU ' || true)
  [[ -z "$NUM_GPUS" ]] && NUM_GPUS=0
  # 500MB 未満を「空き」と判定（CUDA context init で 100-300MB 取られるのは正常範囲）
  for ((i=0; i<NUM_GPUS; i++)); do
    used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "$i" 2>/dev/null | tr -d ' ')
    if [[ -n "$used" && "$used" -lt 500 ]]; then
      FREE_GPUS+=("$i")
    fi
  done
  log "GPU detected (total=$NUM_GPUS, free=${#FREE_GPUS[@]}: ${FREE_GPUS[*]:-none})"
  if (( NUM_GPUS > 0 && ${#FREE_GPUS[@]} == 0 )); then
    log "WARNING: all $NUM_GPUS GPU(s) busy externally; batch mode will run CPU-only"
  fi
else
  log "no GPU detected; running CPU-only"
fi

# 並列バッチ用 GPU ロック ディレクトリ
LOCK_DIR="${LOCK_DIR:-/tmp/paper-reproduce-locks}"
mkdir -p "$LOCK_DIR"

mkdir -p "$HOME/.claude"

# --- Claude 設定ファイルのマウント ---
CLAUDE_JSON_MOUNT=()
if [[ -f "$HOME/.claude.json" ]]; then
  CLAUDE_JSON_MOUNT=(-v "$HOME/.claude.json:/home/claude/.claude.json")
fi

# --- gh 認証トークンの伝播 ---
# コンテナには ~/.config/gh をマウントしないので、host で認証済みの gh から
# トークンを取り出して GH_TOKEN env で渡す。これが無いと experiment-loop /
# Phase 4 の Issue・PR 検索 (scripts/search_github_issues.sh) が gh 未認証扱いで
# スキップされる ("gh/jq が無く...スキップ" の片割れ; gh/jq 本体は Dockerfile で導入済)。
# 値はコマンドラインに出さず env 名のみ渡す (ANTHROPIC_API_KEY と同じ流儀)。
# host に gh が無い / 未認証なら何も渡さず、従来どおり graceful skip にフォールバックする。
GH_TOKEN_FLAGS=()
if command -v gh >/dev/null 2>&1; then
  GH_AUTH_TOKEN="$(gh auth token 2>/dev/null || true)"
  if [[ -n "$GH_AUTH_TOKEN" ]]; then
    export GH_TOKEN="$GH_AUTH_TOKEN"
    GH_TOKEN_FLAGS=(-e GH_TOKEN)
    log "gh auth token detected — propagating to container as GH_TOKEN"
  else
    log "gh present but not authenticated — container Issue search will skip (run: gh auth login)"
  fi
fi

# --- TERM/COLORTERM 伝播 ---
# 未設定だと Docker が TERM=dumb を渡し、Claude Code の Ink TUI が描画されない。
TERM_ENV=(-e "TERM=${TERM:-xterm-256color}")
if [[ -n "${COLORTERM:-}" ]]; then
  TERM_ENV+=(-e "COLORTERM=${COLORTERM}")
fi

# --- ~/.claude 配下の symlink 解決用マウント ---
# dotter 等で ~/.claude/{settings.json,skills/*,CLAUDE.md} が外部 dir への
# symlink になっている場合、マウントしただけだとコンテナ内で切れている。
# 同一パスに read-only でマウントすれば symlink がそのまま辿れる。
SYMLINK_MOUNTS=()
if [[ -d "$HOME/.claude" ]]; then
  declare -A _seen=()
  while IFS= read -r -d '' link; do
    target="$(readlink -f "$link" 2>/dev/null || true)"
    [[ -z "$target" ]] && continue
    [[ "$target" == "$HOME/.claude"* ]] && continue
    [[ "$target" == "$HOME/.claude.json" ]] && continue
    while [[ "$target" != "/" && "$target" != "$HOME" ]]; do
      parent="$(dirname "$target")"
      [[ "$parent" == "$HOME" || "$parent" == "/" ]] && break
      target="$parent"
    done
    [[ -z "${_seen[$target]:-}" && -e "$target" ]] || continue
    _seen[$target]=1
    SYMLINK_MOUNTS+=(-v "$target:$target:ro")
  done < <(find "$HOME/.claude" -maxdepth 4 -type l -print0 2>/dev/null)
fi

# --- ヘルパー: 1 repo の clone（ホスト側）---
clone_one() {
  local url="$1"
  local name dir
  name="$(basename "${url%/}" .git)"
  [[ -n "$name" ]] || die "could not derive repo name from URL: $url"
  dir="$WORKSPACE_DIR/$name"

  if [[ "$FRESH" == "1" && -e "$dir" ]]; then
    log "[$name] --fresh: removing existing clone"
    rm -rf "$dir"
  fi

  if [[ -d "$dir/.git" ]]; then
    log "[$name] already cloned (pass --fresh to re-clone)"
  else
    mkdir -p "$WORKSPACE_DIR"
    log "[$name] cloning $url"
    # --recurse-submodules は意図的に指定しない。/reimplement Phase 2 の
    # divide-and-conquer 戦略で submodule を 1 つずつ追加するため。
    git clone "$url" "$dir"
  fi

  printf '%s\n' "$name"
}

# ==========================================================================
if [[ ${#URLS[@]} -eq 1 ]]; then
  # ---------- 単一モード ----------
  REPO_NAME="$(clone_one "${URLS[0]}")"

  log "starting interactive container at /workspaces/$REPO_NAME"
  log "inside Claude Code, run: /reimplement"

  exec docker run --rm -it \
    -v "$WORKSPACE_DIR:/workspaces" \
    -v "$HOME/.claude:/home/claude/.claude" \
    "${CLAUDE_JSON_MOUNT[@]}" \
    "${SYMLINK_MOUNTS[@]}" \
    "${TERM_ENV[@]}" \
    "${GH_TOKEN_FLAGS[@]}" \
    -e "REPORT_LANG=$REPORT_LANG" \
    -v "$PIXI_CACHE_VOLUME:/home/claude/.cache/rattler" \
    -w "/workspaces/$REPO_NAME" \
    --shm-size=8g \
    "${GPU_FLAGS[@]}" \
    "$IMAGE_NAME"
fi

# ---------- 並列バッチモード (tmux) ----------
command -v tmux  >/dev/null 2>&1 || die "tmux not found on PATH (required for batch mode)"
command -v flock >/dev/null 2>&1 || die "flock not found on PATH (util-linux; required for batch GPU lock)"

SESSION_NAME="paper-reproduce-$(date +%H%M%S)"

# 全 repo を clone
REPO_NAMES=()
for url in "${URLS[@]}"; do
  name="$(clone_one "$url")"
  REPO_NAMES+=("$name")
done

ENV_FLAGS=()
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  ENV_FLAGS+=(-e ANTHROPIC_API_KEY)
fi

# docker run コマンドを組み立てるヘルパー
docker_cmd_for() {
  local idx="$1"
  local name="${REPO_NAMES[idx]}"

  # 並列バッチは --gpus "device=N" で 1 GPU だけをコンテナに公開し、
  # flock でそのスロットを 1 ジョブに排他。重複起動時は flock が後続を直列化する。
  # FREE_GPUS が空 (CPU-only or 全 GPU 占有中) のときは GPU 関連フラグを付けない。
  local gpu_args=()
  local prefix=""
  if (( ${#FREE_GPUS[@]} > 0 )); then
    local gpu_idx="${FREE_GPUS[$(( idx % ${#FREE_GPUS[@]} ))]}"
    gpu_args=(--gpus "device=$gpu_idx")
    prefix="flock -x $LOCK_DIR/gpu-$gpu_idx.lock"
  fi

  echo $prefix docker run --rm -it \
    -v "$WORKSPACE_DIR:/workspaces" \
    -v "$HOME/.claude:/home/claude/.claude" \
    "${CLAUDE_JSON_MOUNT[@]}" \
    "${SYMLINK_MOUNTS[@]}" \
    "${TERM_ENV[@]}" \
    "${GH_TOKEN_FLAGS[@]}" \
    -e "REPORT_LANG=$REPORT_LANG" \
    -v "$PIXI_CACHE_VOLUME:/home/claude/.cache/rattler" \
    -w "/workspaces/$name" \
    --shm-size=8g \
    "${gpu_args[@]}" \
    "${ENV_FLAGS[@]}" \
    "$IMAGE_NAME"
}

# 最初の repo で tmux セッションを作成
log "creating tmux session: $SESSION_NAME"
tmux new-session -d -s "$SESSION_NAME" -n "${REPO_NAMES[0]}" \
  "$(docker_cmd_for 0)"

# 残りの repo を tmux ウィンドウとして追加
for i in $(seq 1 $(( ${#REPO_NAMES[@]} - 1 ))); do
  tmux new-window -t "$SESSION_NAME" -n "${REPO_NAMES[i]}" \
    "$(docker_cmd_for "$i")"
done

log "launched ${#REPO_NAMES[@]} containers in tmux session: $SESSION_NAME"
log "inside each Claude Code, run: /reimplement"
log "tmux cheat sheet:"
log "  Ctrl+b → n  next window"
log "  Ctrl+b → p  previous window"
log "  Ctrl+b → 0  jump to window 0"
log "  Ctrl+b → d  detach (containers keep running)"

# tmux にアタッチ
if [[ -n "${TMUX:-}" ]]; then
  exec tmux switch-client -t "$SESSION_NAME"
else
  exec tmux attach -t "$SESSION_NAME"
fi
