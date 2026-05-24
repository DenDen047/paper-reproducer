#!/usr/bin/env bash
# Docker は named volume のマウント親ディレクトリを root 所有で作るため、
# claude ユーザーが .cache 配下に書けなくなる。起動時にその所有権を戻す保険
set -e

for d in /home/claude/.cache /home/claude/.cache/rattler; do
  if [[ -d "$d" ]] && [[ "$(stat -c %U "$d" 2>/dev/null)" != "claude" ]]; then
    sudo chown claude:claude "$d" 2>/dev/null || true
  fi
done

# open3d 0.19+ は libc 2.31 以上必須
libc_ver=$(ldd --version 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
if [[ -n "$libc_ver" ]] && [[ "$(printf '%s\n2.31\n' "$libc_ver" | sort -V | head -1)" == "$libc_ver" ]] && [[ "$libc_ver" != "2.31" ]]; then
  echo "[entrypoint] WARN: libc $libc_ver < 2.31 — open3d 0.19+ may fail to install" >&2
fi

# モデルは host の ~/.claude/settings.json (model: opus[1m]) をそのまま継承する。
# opus[1m] (1M context) は Claude Code <2.1.144 + サブスク(OAuth)認証で
# "400 role 'system' is not supported on this model" を返すため、image 内の
# claude が新しいことが前提 (Dockerfile の CLAUDE_CODE_BUILD cache-bust で担保)。
exec claude \
  --dangerously-skip-permissions \
  --plugin-dir /paper-reproduce-skills \
  "$@"
