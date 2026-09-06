# D-10: development environment pinned to the same versions the project pins
# elsewhere — Python 3.13, Node 24, pnpm 10.34.5, uv >=0.12,<0.13, and Rust
# 1.98.0 (vendor/nautilus_trader/rust-toolchain.toml). A mismatch between this
# container and the submodule's pinned channel is precisely the two-machine
# divergence success criterion 2 forbids.
FROM mcr.microsoft.com/devcontainers/base:noble

ARG PYTHON_VERSION=3.13
ARG NODE_VERSION=24
ARG PNPM_VERSION=10.34.5
ARG UV_VERSION=0.12.0
ARG RUST_CHANNEL=1.98.0

# Node — via nodesource, then pnpm pinned through corepack (already ships
# with Node) rather than a separate global npm install.
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && corepack enable \
    && corepack prepare pnpm@${PNPM_VERSION} --activate \
    && rm -rf /var/lib/apt/lists/*

# uv manages its own pinned Python — no system Python / deadsnakes needed.
ENV PATH=/usr/local/bin:$PATH
RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh \
    && uv python install ${PYTHON_VERSION}

# Rust, pinned to the submodule's exact channel. rustup resolves
# vendor/nautilus_trader/rust-toolchain.toml's override automatically once
# a shell's cwd is inside the submodule.
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
    sh -s -- -y --default-toolchain ${RUST_CHANNEL} --profile minimal \
    && chmod -R a+w /usr/local/rustup /usr/local/cargo

USER vscode
