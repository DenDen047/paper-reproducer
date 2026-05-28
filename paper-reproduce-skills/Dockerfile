FROM ghcr.io/prefix-dev/pixi:jammy

# CV論文リポジトリは libgl, ffmpeg 等を暗黙に要求することが多い
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    wget \
    unzip \
    ca-certificates \
    sudo \
    # CV 論文でほぼ必須のシステムライブラリ
    libgl1-mesa-glx \
    libglib2.0-0 \
    libgomp1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Node.js は MCP サーバ等が要求する可能性があるため残す
# (Claude Code 本体は native binary なので Node ランタイムには依存しない)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY . /paper-reproduce-skills

RUN mkdir -p /etc/headless_patches \
    && cp /paper-reproduce-skills/headless_patch.py /etc/headless_patches/headless_patch.py \
    && chmod 0644 /etc/headless_patches/headless_patch.py

# --dangerously-skip-permissions は root では使えないため非 root ユーザーで実行
# UID/GID は host ユーザーに合わせる。bind-mount された ~/.claude(.json) を読むのに必須。
ARG USER_UID=1000
ARG USER_GID=1000
RUN groupadd -g ${USER_GID} claude \
    && useradd -m -s /bin/bash -u ${USER_UID} -g ${USER_GID} claude \
    && chown -R claude:claude /paper-reproduce-skills \
    && echo "claude ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Cache ディレクトリを事前に作っておく
RUN mkdir -p /home/claude/.cache/rattler \
    && chown -R claude:claude /home/claude/.cache

# Entrypoint wrapper: 既存の壊れた named volume に対する保険
COPY --chmod=0755 entrypoint.sh /usr/local/bin/entrypoint.sh

USER claude

# Claude Code 本体は native installer で claude ユーザーのホームに置く。
# `npm install -g` だと /usr/lib/node_modules/ が root 所有になり、
# 非 root 実行下では auto-update が失敗するため。
# https://code.claude.com/docs/en/setup
#
# install.sh は常に最新版を入れるが、この RUN は Docker layer cache に乗るため
# 一度ビルドすると古い版に固定される (例: 2026-05-10 ビルドの image は 2.1.138)。
# opus[1m] (1M context) は host settings.json の model エイリアスで、最新の Opus
# (現在は Claude Opus 4.8) に解決される。古い Claude Code (2.1.144 より前) は
# サブスク認証下でこれを扱えず "400 role 'system' is not supported on this model"
# を返すので、最新版を確実に入れ直せるよう CLAUDE_CODE_BUILD で cache を破棄できるようにする。
# bootstrap.sh が build 毎に日付を渡すため、--rebuild すれば必ず最新版を取得する。
ARG CLAUDE_CODE_BUILD=unset
RUN curl -fsSL https://claude.ai/install.sh | bash

# bootstrap.sh が host の ~/.claude/settings.json を mount するため、
# host 側の PreToolUse:Bash hook (rtk hook claude) が container 内にも見える。
# rtk が無いと全 Bash コマンドの直前で hook が失敗するので container にも入れる。
# check-jsonschema は Phase 1 / Phase 4 の schema gate で使う (analysis.json /
# report.json の structural invariants を機械検証する)。
# gh / jq は experiment-loop と Phase 4 の Issue/PR 検索
# (scripts/search_github_issues.sh) と analysis.json の jq パースに必須。
# 無いと "gh/jq が無く Phase 4 では関連 Issue 検索をスキップ" になる。
# pixi-only ポリシーに従い conda-forge から入れる (apt/brew は使わない)。
RUN pixi global install rtk-cli check-jsonschema gh jq

ENV PATH=/home/claude/.pixi/bin:/home/claude/.local/bin:$PATH

WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
