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

# Claude Code は Node.js ランタイムが必要
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @anthropic-ai/claude-code

# pueue: バッチ処理用タスクキュー（複数リポジトリの連続実行に使用）
RUN curl -fsSL https://github.com/Nukesor/pueue/releases/latest/download/pueued-x86_64-unknown-linux-musl -o /usr/local/bin/pueued \
    && curl -fsSL https://github.com/Nukesor/pueue/releases/latest/download/pueue-x86_64-unknown-linux-musl -o /usr/local/bin/pueue \
    && chmod +x /usr/local/bin/pueued /usr/local/bin/pueue

COPY . /paper-reproduce-skills

# --dangerously-skip-permissions は root では使えないため非 root ユーザーで実行
RUN useradd -m -s /bin/bash claude \
    && chown -R claude:claude /paper-reproduce-skills \
    && echo "claude ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

USER claude

WORKDIR /workspace

# インタラクティブ起動
ENTRYPOINT ["claude", \
    "--dangerously-skip-permissions", \
    "--plugin-dir", "/paper-reproduce-skills"]
