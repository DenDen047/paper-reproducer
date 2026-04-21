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
  -h, --help         Show this help

Environment:
  WORKSPACE_DIR      Host clone dir (default: ~/paper-reproduce-workspaces)

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

# --- 事前チェック（共通）---
command -v git     >/dev/null 2>&1 || die "git not found on PATH"
command -v docker  >/dev/null 2>&1 || die "docker not found on PATH"
command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH (required for batch summary)"
[[ -f "$DOCKERFILE_DIR/Dockerfile" ]] || die "Dockerfile not found at $DOCKERFILE_DIR"

# --- Docker イメージのビルド（共通）---
if [[ "$REBUILD" == "1" ]] || ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
  log "building image: $IMAGE_NAME"
  docker build -t "$IMAGE_NAME" "$DOCKERFILE_DIR"
else
  log "image $IMAGE_NAME already present (use --rebuild to force)"
fi

# --- GPU 検出 + 枚数カウント ---
GPU_FLAGS=()
NUM_GPUS=0
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  GPU_FLAGS=(--gpus all)
  # nvidia-smi -L の行数が GPU 枚数
  NUM_GPUS=$(nvidia-smi -L 2>/dev/null | grep -c '^GPU ' || true)
  [[ -z "$NUM_GPUS" ]] && NUM_GPUS=0
  log "GPU detected (count=$NUM_GPUS); passing --gpus all"
else
  log "no GPU detected; running CPU-only"
fi

mkdir -p "$HOME/.claude"

# --- Claude 設定ファイルのマウント ---
CLAUDE_JSON_MOUNT=()
if [[ -f "$HOME/.claude.json" ]]; then
  CLAUDE_JSON_MOUNT=(-v "$HOME/.claude.json:/home/claude/.claude.json")
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
    -v "$PIXI_CACHE_VOLUME:/home/claude/.cache/rattler" \
    -w "/workspaces/$REPO_NAME" \
    --shm-size=8g \
    "${GPU_FLAGS[@]}" \
    "$IMAGE_NAME"
fi

# ---------- 並列バッチモード (tmux) ----------
command -v tmux >/dev/null 2>&1 || die "tmux not found on PATH (required for batch mode)"

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

  local gpu_env=()
  if (( NUM_GPUS > 0 )); then
    local gpu_idx=$(( idx % NUM_GPUS ))
    gpu_env=(-e "CUDA_VISIBLE_DEVICES=$gpu_idx")
  fi

  echo docker run --rm -it \
    -v "$WORKSPACE_DIR:/workspaces" \
    -v "$HOME/.claude:/home/claude/.claude" \
    "${CLAUDE_JSON_MOUNT[@]}" \
    -v "$PIXI_CACHE_VOLUME:/home/claude/.cache/rattler" \
    -w "/workspaces/$name" \
    --shm-size=8g \
    "${GPU_FLAGS[@]}" \
    "${gpu_env[@]}" \
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
