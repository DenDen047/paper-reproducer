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
# ライセンス登録が必須で自動 DL できない手動資産 (SMPL/SMAL 系等) の「正本」置き場。
# 既定はプロジェクト内で完結する <repo>/manual-assets (.gitignore 済み: ライセンス
# ファイルを git/イメージに入れないため)。これを正本として常にここで管理する。
# 実際にコンテナへマウントするのはこの正本を複製した非暗号 staging (後段参照);
# 正本が非暗号なら複製は不要でそのままマウントする (registry/ASSETS.md 参照)。
MANUAL_ASSETS_DIR="${MANUAL_ASSETS_DIR:-$SCRIPT_DIR/manual-assets}"
# staging の置き場所。$WORKSPACE_DIR 配下は禁止: /workspaces として rw マウント
# されるため :ro 資産が rw でも見えてしまい、"manual-assets" という名前の repo
# clone とも衝突する。
MANUAL_ASSETS_STAGING="${MANUAL_ASSETS_STAGING:-$HOME/.cache/paper-reproduce/manual-assets}"

REBUILD=0
FRESH=0
REPOS_FILE=""
URLS=()
LIST_ASSETS=0
REPORT_LANG="${REPORT_LANG:-ja}"
# 再現レベル: inference (既定) = 推論再現まで / full = 学習 + claim 定量評価まで。
# claim の抽出・表示はどちらでも行うが、時間のかかる training / eval は full のみ。
REPRODUCE_LEVEL="${REPRODUCE_LEVEL:-inference}"
# コンテナ内 Claude Code のモデル/effort。host の ~/.claude/settings.json の model
# (現在 fable-5) を継承させず、再現ジョブは Opus に固定する。opus[1m] は 1M context
# の最新 Opus エイリアス (現在 Claude Opus 4.8 に解決)。entrypoint.sh が "$@" 経由で
# claude に転送するため、既存 image のまま (再ビルドなしで) 効く。
REPRODUCE_MODEL="${REPRODUCE_MODEL:-opus[1m]}"
REPRODUCE_EFFORT="${REPRODUCE_EFFORT:-xhigh}"

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
  --full             Full verification: training + quantitative claim eval
                     (default is inference-level reproduction only)
  --lang <code>      Report output language: ja (default) | en
  --list-assets      Show manual-asset registry status (license-gated models) and exit
  -h, --help         Show this help

Environment:
  WORKSPACE_DIR         Host clone dir (default: ~/paper-reproduce-workspaces)
  MANUAL_ASSETS_DIR     License-gated asset dir (default: ./manual-assets, gitignored)
  MANUAL_ASSETS_STAGING Non-FUSE staging copy for Docker mount
                        (default: ~/.cache/paper-reproduce/manual-assets)
  REPORT_LANG           Same as --lang (default: ja); overridden by --lang
  REPRODUCE_LEVEL       inference (default) | full; --full sets full
  REPRODUCE_MODEL       Claude model inside the container (default: opus[1m],
                        currently resolves to Claude Opus 4.8)
  REPRODUCE_EFFORT      Reasoning effort: low|medium|high|xhigh|max (default: xhigh)

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
    --full)    REPRODUCE_LEVEL=full; shift ;;
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
    --list-assets) LIST_ASSETS=1; shift ;;
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

MANUAL_ASSETS_SCRIPT="$DOCKERFILE_DIR/scripts/provision_manual_assets.py"
MANUAL_ASSETS_MANIFEST="$DOCKERFILE_DIR/registry/manifest.json"

# --list-assets: レジストリ状態を表示して終了 (URL 不要)
if [[ "$LIST_ASSETS" == "1" ]]; then
  command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH (required for --list-assets)"
  python3 "$MANUAL_ASSETS_SCRIPT" inventory \
    --root "$MANUAL_ASSETS_DIR" --manifest "$MANUAL_ASSETS_MANIFEST" \
    --lang "${REPORT_LANG:-ja}" --list
  exit 0
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

case "$REPRODUCE_LEVEL" in
  inference|full) ;;
  *) die "unsupported REPRODUCE_LEVEL '$REPRODUCE_LEVEL' (expected: inference | full)" ;;
esac
log "reproduce level: $REPRODUCE_LEVEL"

case "$REPRODUCE_EFFORT" in
  low|medium|high|xhigh|max) ;;
  *) die "unsupported REPRODUCE_EFFORT '$REPRODUCE_EFFORT' (expected: low | medium | high | xhigh | max)" ;;
esac
log "claude model: $REPRODUCE_MODEL (effort: $REPRODUCE_EFFORT)"

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
  # CLAUDE_CODE_BUILD で install.sh layer の cache を破棄し最新の Claude Code を
  # 取り直す (opus[1m] を扱える ≥2.1.144 を確実に入れるため。Dockerfile 参照)。
  # 自動ビルドは日単位 (日次で十分な鮮度)、明示的な --rebuild は秒単位で必ず破棄
  # (日単位だと同日 2 回目の --rebuild が cache hit して更新されない)。
  if [[ "$REBUILD" == "1" ]]; then
    CLAUDE_CODE_BUILD="$(date +%Y%m%d%H%M%S)"
  else
    CLAUDE_CODE_BUILD="$(date +%Y%m%d)"
  fi
  docker build \
    --build-arg "USER_UID=${HOST_UID}" \
    --build-arg "USER_GID=${HOST_GID}" \
    --build-arg "CLAUDE_CODE_BUILD=$CLAUDE_CODE_BUILD" \
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

# --- HuggingFace 認証 / キャッシュの伝播 ---
# 一部の gated モデル (facebook 製等) は申請済みアカウントのトークンが無いと
# DL できない。host の HF 認証とモデルキャッシュをコンテナに引き継ぐ:
#   (1) host の HF cache dir を mount → token ファイル + hub/xet キャッシュを共有。
#       gated モデルの host 既 DL 分を再利用でき、再 DL を避けられる。
#       コンテナの claude user は host UID に揃えてあるので読み書きできる。
#   (2) env / token ファイルから HF_TOKEN を解決し env でも渡す
#       (token をファイル化せず env だけで持つケースの保険; 値はコマンドライン
#        に出さず env 名のみ渡す = GH_TOKEN と同じ流儀)。
# host に HF 認証もキャッシュも無ければ何も渡さず、従来どおり public DL のみで進む。
HF_HOME_DIR="${HF_HOME:-$HOME/.cache/huggingface}"
HF_CACHE_MOUNT=()
if [[ -d "$HF_HOME_DIR" ]]; then
  HF_CACHE_MOUNT=(-v "$HF_HOME_DIR:/home/claude/.cache/huggingface")
  log "mounting HuggingFace cache: $HF_HOME_DIR (token + model cache shared)"
fi
HF_TOKEN_FLAGS=()
HF_AUTH_TOKEN="${HF_TOKEN:-${HUGGING_FACE_HUB_TOKEN:-}}"
if [[ -z "$HF_AUTH_TOKEN" ]]; then
  for _hf_tok_file in "$HF_HOME_DIR/token" "$HOME/.huggingface/token"; do
    if [[ -f "$_hf_tok_file" ]]; then
      HF_AUTH_TOKEN="$(tr -d '[:space:]' < "$_hf_tok_file")"
      [[ -n "$HF_AUTH_TOKEN" ]] && break
    fi
  done
fi
if [[ -n "$HF_AUTH_TOKEN" ]]; then
  export HF_TOKEN="$HF_AUTH_TOKEN"
  HF_TOKEN_FLAGS=(-e HF_TOKEN)
  log "HuggingFace token detected — propagating to container as HF_TOKEN"
elif [[ ${#HF_CACHE_MOUNT[@]} -eq 0 ]]; then
  log "no HuggingFace auth/cache on host — gated models may be unavailable (run: huggingface-cli login)"
fi

# --- 手動 provisioning 資産レジストリのマウント + 初回案内 ---
# SMPL/SMAL 系のようにライセンス登録が必須で自動 DL できない資産は、ユーザーが
# 一度だけ手作業で正本 ($MANUAL_ASSETS_DIR) に置けば、コンテナ内の /reimplement が
# repo の期待パスへ自動配置する。ここでは (1) 正本を非暗号 staging へ複製して
# read-only マウントし、(2) 未作成/欠落があれば取得 URL 付きの案内を出す
# (graceful、未配置でも続行)。bootstrap 時点では対象 repo 未解析なので案内は
# repo 非依存の一般ヒント; repo 固有の必須判定はコンテナ内 Phase 3 が行う。
#
# なぜ複製してマウントするか: Docker daemon は root で動くが、user_id=<uid> かつ
# allow_other 無しの FUSE (gocryptfs 等) は root が辿れず、そこを bind-mount すると
# "mkdir <mountpoint>: file exists" で起動失敗する。repo が ~/Documents (gocryptfs)
# 配下だと正本 $SCRIPT_DIR/manual-assets が必ずこれに当たる。そこで正本が FUSE 上の
# ときだけ $MANUAL_ASSETS_STAGING へ rsync 複製し、その複製をマウントする。
#
# 複製は background で行い docker run をブロックしない (資産更新直後は数十 GB の
# 転送になり得るため)。同期完了は staging 直下の .sync-complete マーカーで通知し、
# コンテナ内の manual-asset-provisioner が Phase 3 Step 1.0 (起動から数十分後) で
# マーカーを待つ。マーカーは起動時に必ず消し、flock 排他の同期ジョブだけが再作成
# する (並行 bootstrap の rsync --delete 競合と stale マーカーの両方を防ぐ)。
MANUAL_ASSETS_MOUNT=()
MANUAL_ASSETS_ENV=()
MANUAL_ASSETS_MOUNT_SRC="$MANUAL_ASSETS_DIR"
if [[ -d "$MANUAL_ASSETS_DIR" ]]; then
  _assets_fstype=""
  if command -v findmnt >/dev/null 2>&1; then
    _assets_fstype="$(findmnt -no FSTYPE --target "$MANUAL_ASSETS_DIR" 2>/dev/null || true)"
  else
    log "WARNING: findmnt not found — FUSE 判定不可のため正本を直接マウントする (gocryptfs 上なら docker run が失敗する)"
  fi
  if [[ "$_assets_fstype" == fuse* ]]; then
    command -v rsync >/dev/null 2>&1 || die "rsync not found; required to stage manual-assets off $_assets_fstype"
    command -v flock >/dev/null 2>&1 || die "flock not found (util-linux); required to stage manual-assets"
    MANUAL_ASSETS_MOUNT_SRC="$MANUAL_ASSETS_STAGING"
    mkdir -p "$MANUAL_ASSETS_MOUNT_SRC"
    _sync_marker="$MANUAL_ASSETS_MOUNT_SRC/.sync-complete"
    _sync_lock="$LOCK_DIR/manual-assets-staging.lock"
    rm -f "$_sync_marker"
    log "manual-assets 正本が $_assets_fstype 上 (Docker が bind-mount 不可) → $MANUAL_ASSETS_MOUNT_SRC へ background 同期 (完了 = .sync-complete)"
    (
      flock -x 9
      # 変更なし (dry-run 空) なら転送せず即マーカー。--partial で中断済み転送を再開可能に。
      if [[ -n "$(rsync -a --delete --dry-run --out-format='%n' "$MANUAL_ASSETS_DIR/" "$MANUAL_ASSETS_MOUNT_SRC/" | head -1)" ]]; then
        rsync -a --delete --partial "$MANUAL_ASSETS_DIR/" "$MANUAL_ASSETS_MOUNT_SRC/"
      fi
      date -u +%Y-%m-%dT%H:%M:%SZ > "$_sync_marker"
    ) 9>"$_sync_lock" >"$MANUAL_ASSETS_MOUNT_SRC/.sync.log" 2>&1 &
    disown
    MANUAL_ASSETS_ENV=(-e "MANUAL_ASSETS_READY_MARKER=/manual-assets/.sync-complete")
    # 旧 staging (v0.1.6 以前は $WORKSPACE_DIR/manual-assets) が残っていたら案内
    if [[ -d "$WORKSPACE_DIR/manual-assets" ]]; then
      log "NOTE: 旧 staging $WORKSPACE_DIR/manual-assets が残っています (現在は未使用)。容量回収: rm -rf '$WORKSPACE_DIR/manual-assets'"
    fi
  fi
  MANUAL_ASSETS_MOUNT=(-v "$MANUAL_ASSETS_MOUNT_SRC:/manual-assets:ro")
fi
if [[ -f "$MANUAL_ASSETS_SCRIPT" ]]; then
  # 完備なら 1 行、未作成/一部欠落なら取得 URL 付きの構造化ブロックを出す。
  # 案内は正本 ($MANUAL_ASSETS_DIR) を基準に出す (ユーザーが資産を置く場所)。
  python3 "$MANUAL_ASSETS_SCRIPT" inventory \
    --root "$MANUAL_ASSETS_DIR" --manifest "$MANUAL_ASSETS_MANIFEST" \
    --lang "$REPORT_LANG" 2>/dev/null \
    | while IFS= read -r _line; do log "$_line"; done || true
fi

# --- ANTHROPIC_API_KEY 伝播 (single / batch 共通) ---
# 値はコマンドラインに出さず env 名のみ渡す (GH_TOKEN と同じ流儀)。
ENV_FLAGS=()
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  ENV_FLAGS+=(-e ANTHROPIC_API_KEY)
fi

# --- コンテナ内 claude への CLI 引数 (single / batch 共通) ---
# image 名の後ろに置くと docker の CMD になり、entrypoint.sh の "$@" が claude に
# 転送する。CLI 引数は mount された settings.json の model 設定より優先される。
CLAUDE_ARGS=(--model "$REPRODUCE_MODEL" --effort "$REPRODUCE_EFFORT")

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
    "${HF_TOKEN_FLAGS[@]}" \
    "${HF_CACHE_MOUNT[@]}" \
    "${MANUAL_ASSETS_MOUNT[@]}" \
    "${MANUAL_ASSETS_ENV[@]}" \
    "${ENV_FLAGS[@]}" \
    -e "REPORT_LANG=$REPORT_LANG" \
    -e "REPRODUCE_LEVEL=$REPRODUCE_LEVEL" \
    -v "$PIXI_CACHE_VOLUME:/home/claude/.cache/rattler" \
    -w "/workspaces/$REPO_NAME" \
    --shm-size=8g \
    "${GPU_FLAGS[@]}" \
    "$IMAGE_NAME" \
    "${CLAUDE_ARGS[@]}"
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

# tmux に渡すコマンドを echo で 1 本の文字列に潰すと配列の quoting が失われ、
# スペース / グロブ / $ を含むパスで -v 引数が壊れる。repo ごとに %q で quoting を
# 保存したラッパースクリプトを生成し、tmux にはそのパスだけを渡す。
# スクリプトは mktemp -d 配下 (session 終了後は /tmp 掃除に任せる)。
BATCH_CMD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/paper-reproduce-batch.XXXXXX")"

write_batch_script() {
  local idx="$1"
  local name="${REPO_NAMES[idx]}"
  local script="$BATCH_CMD_DIR/run-$idx-$name.sh"

  # 並列バッチは --gpus "device=N" で 1 GPU だけをコンテナに公開し、
  # flock でそのスロットを 1 ジョブに排他。重複起動時は flock が後続を直列化する。
  # FREE_GPUS が空 (CPU-only or 全 GPU 占有中) のときは GPU 関連フラグを付けない。
  local gpu_args=()
  local prefix=()
  if (( ${#FREE_GPUS[@]} > 0 )); then
    local gpu_idx="${FREE_GPUS[$(( idx % ${#FREE_GPUS[@]} ))]}"
    gpu_args=(--gpus "device=$gpu_idx")
    prefix=(flock -x "$LOCK_DIR/gpu-$gpu_idx.lock")
  fi

  local cmd=("${prefix[@]}" docker run --rm -it
    -v "$WORKSPACE_DIR:/workspaces"
    -v "$HOME/.claude:/home/claude/.claude"
    "${CLAUDE_JSON_MOUNT[@]}"
    "${SYMLINK_MOUNTS[@]}"
    "${TERM_ENV[@]}"
    "${GH_TOKEN_FLAGS[@]}"
    "${HF_TOKEN_FLAGS[@]}"
    "${HF_CACHE_MOUNT[@]}"
    "${MANUAL_ASSETS_MOUNT[@]}"
    "${MANUAL_ASSETS_ENV[@]}"
    -e "REPORT_LANG=$REPORT_LANG"
    -e "REPRODUCE_LEVEL=$REPRODUCE_LEVEL"
    -v "$PIXI_CACHE_VOLUME:/home/claude/.cache/rattler"
    -w "/workspaces/$name"
    --shm-size=8g
    "${gpu_args[@]}"
    "${ENV_FLAGS[@]}"
    "$IMAGE_NAME"
    "${CLAUDE_ARGS[@]}")

  {
    printf '#!/usr/bin/env bash\nexec'
    printf ' %q' "${cmd[@]}"
    printf '\n'
  } > "$script"
  chmod +x "$script"
  printf '%s\n' "$script"
}

# 最初の repo で tmux セッションを作成
log "creating tmux session: $SESSION_NAME"
tmux new-session -d -s "$SESSION_NAME" -n "${REPO_NAMES[0]}" \
  "$(write_batch_script 0)"

# 残りの repo を tmux ウィンドウとして追加
for i in $(seq 1 $(( ${#REPO_NAMES[@]} - 1 ))); do
  tmux new-window -t "$SESSION_NAME" -n "${REPO_NAMES[i]}" \
    "$(write_batch_script "$i")"
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
