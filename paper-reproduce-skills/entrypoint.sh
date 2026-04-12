#!/usr/bin/env bash
# Docker は named volume のマウント親ディレクトリを root 所有で作るため、
# claude ユーザーが .cache 配下に書けなくなる。起動時にその所有権を戻す保険
set -e

for d in /home/claude/.cache /home/claude/.cache/rattler; do
  if [[ -d "$d" ]] && [[ "$(stat -c %U "$d" 2>/dev/null)" != "claude" ]]; then
    sudo chown claude:claude "$d" 2>/dev/null || true
  fi
done

exec claude \
  --dangerously-skip-permissions \
  --plugin-dir /paper-reproduce-skills \
  "$@"
