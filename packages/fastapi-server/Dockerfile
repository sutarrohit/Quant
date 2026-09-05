# syntax=docker/dockerfile:1
#
# FastAPI blog API (@repo/fastapi-server) — multi-stage build.
#
# IMPORTANT: the build context is THIS directory, not the repository root: the
# package is self-contained (uv + pyproject.toml) and does not depend on the
# pnpm workspace. docker-compose.yml sets `context: .` accordingly.
#
# Stages:
#   base       uv + python 3.13, shared by every build stage
#   deps       third-party dependencies only, resolved from pyproject.toml and
#              uv.lock -- cached until one of those two files changes
#   build      the application source on top of that venv
#   runtime    a plain python image plus the finished venv, as a non-root user
#
# uv itself only exists in the build stages; the runtime image ships the venv.

# ------------------------------------------------------------------- base
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS base

# COMPILE_BYTECODE trades build time for faster cold starts; LINK_MODE=copy
# avoids hardlink warnings when the uv cache is a separate mount (below);
# PYTHON_DOWNLOADS=never keeps uv on the interpreter already in the image.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app


# ------------------------------------------------------------------- deps
# Only the two dependency manifests are copied, so this layer -- the expensive
# one -- survives every source-only change. --no-install-project leaves the app
# itself out; it arrives in the next stage.
FROM base AS deps

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# ------------------------------------------------------------------ build
# Source on top of the cached venv. The second sync is a no-op for third-party
# packages and only wires up the project itself. --no-dev keeps pytest, ruff and
# httpx out of the image.
FROM deps AS build

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# ---------------------------------------------------------------- runtime
FROM python:3.13-slim-bookworm AS runtime

# The app user must own /app so the default sqlite file can be created there.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app && chown app:app /app
WORKDIR /app

# The venv is relocatable only at this exact path, hence /app -> /app.
COPY --from=build --chown=app:app /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    ENVIRONMENT=production \
    PYTHONUNBUFFERED=1

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

CMD ["fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8000"]
