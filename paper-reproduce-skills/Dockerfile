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

COPY . /paper-reproduce-skills

RUN mkdir -p /etc/headless_patches \
    && cp /paper-reproduce-skills/headless_patch.py /etc/headless_patches/headless_patch.py \
    && chmod 0644 /etc/headless_patches/headless_patch.py

# --dangerously-skip-permissions は root では使えないため非 root ユーザーで実行
RUN useradd -m -s /bin/bash claude \
    && chown -R claude:claude /paper-reproduce-skills \
    && echo "claude ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Cache ディレクトリを事前に作っておく
RUN mkdir -p /home/claude/.cache/rattler \
    && chown -R claude:claude /home/claude/.cache

# Entrypoint wrapper: 既存の壊れた named volume に対する保険
COPY --chmod=0755 entrypoint.sh /usr/local/bin/entrypoint.sh

USER claude

WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
