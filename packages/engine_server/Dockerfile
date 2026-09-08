# syntax=docker/dockerfile:1
#
# NautilusTrader service -- multi-stage build.
#
# The build context is THIS directory; the package is self-contained (uv +
# pyproject.toml).
#
# Three runtime targets, because the spec (section 0) forbids merging them:
#   api      FastAPI process. Enqueues jobs. Must never run a backtest.
#   worker   arq process. Runs BacktestNode, pins a CPU, gets recycled.
#   live     Supervisor process. Converges accounts on their desired state.
#
# Stages:
#   base     uv + python 3.13, shared by every build stage
#   deps     third-party dependencies only -- cached until pyproject/uv.lock change
#   build    application source on top of that venv
#   api      runtime image serving HTTP
#   worker   runtime image draining the job queue
#   live     runtime image running the live control plane

# ------------------------------------------------------------------- base
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS base

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# ------------------------------------------------------------------- deps
FROM base AS deps

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# ------------------------------------------------------------------ build
FROM deps AS build

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --------------------------------------------------------------- runtime
FROM python:3.13-slim-bookworm AS runtime

# The app user must own the catalog/artifact mount points.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app /data/catalog /data/raw /data/artifacts /data/kill \
    && chown -R app:app /app /data
WORKDIR /app

# The venv is relocatable only at this exact path, hence /app -> /app.
COPY --from=build --chown=app:app /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    NT_CATALOG_PATH=/data/catalog \
    NT_RAW_PATH=/data/raw \
    NT_ARTIFACT_PATH=/data/artifacts

USER app

# ------------------------------------------------------------------- api
FROM runtime AS api

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

CMD ["fastapi", "run", "src/engine/api/app.py", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------- worker
FROM runtime AS worker

# Wired up in Step 15; the target exists now so compose can reference it.
CMD ["arq", "engine.worker.main.WorkerSettings"]

# ------------------------------------------------------------------ live
FROM runtime AS live

# The on-disk kill switch. Mounted from the host in compose, so an operator can
# stop an account with `touch` when Redis or the API is unreachable -- which is
# exactly when they are most likely to want to.
ENV NT_LIVE_KILL_SWITCH_DIR=/data/kill

# Not `exec`-wrapped by a shell: SIGTERM must reach Python directly, because
# the shutdown path is what releases the leases and hands the accounts back.
# A shell would swallow it and the accounts would wait out a heartbeat timeout.
STOPSIGNAL SIGTERM

CMD ["python", "-m", "engine.live.main"]
