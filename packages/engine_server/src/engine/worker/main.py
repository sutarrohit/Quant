"""arq worker entry point.

    uv run arq engine.worker.main.WorkerSettings

Deliberate settings, each for a reason:

``max_jobs = 1``
    A backtest saturates a core. Running several per process would make them
    contend and make the timeout meaningless. Scale by adding workers.

``max_tries = 1``
    A backtest that failed will fail again -- the inputs are identical and the
    run is deterministic. Retrying burns a CPU for minutes to reach the same
    answer, and would double-charge a caller polling for a result.

``job_timeout``
    A backstop above the runner's own ceiling. The runner kills the child
    process; this only fires if that mechanism itself wedges.

Redis here is the arq queue. Phase 5's Nautilus cache database must use a
different logical DB: a FLUSHDB aimed at this queue must never be able to
erase live trading state (spec section 9.2).
"""

from __future__ import annotations

import logging
from typing import Any

import redis.asyncio as aioredis
from arq.connections import RedisSettings

from engine.logging import configure_logging
from engine.settings import Settings, get_settings
from engine.store.jobs import JobStore
from engine.worker.tasks import run_backtest

logger = logging.getLogger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    redis = aioredis.from_url(  # type: ignore[no-untyped-call]
        settings.redis_url, decode_responses=True
    )
    ctx["settings"] = settings
    ctx["redis"] = redis
    ctx["job_store"] = JobStore.from_settings(settings, redis)
    logger.info(
        "worker started",
        extra={"catalog": settings.catalog_path, "timeout_s": settings.backtest_timeout_seconds},
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    redis = ctx.get("redis")
    if redis is not None:
        await redis.aclose()
    logger.info("worker stopped")


def _redis_settings(settings: Settings | None = None) -> RedisSettings:
    return RedisSettings.from_dsn((settings or get_settings()).redis_url)


class WorkerSettings:
    functions = [run_backtest]
    on_startup = startup
    on_shutdown = shutdown

    max_jobs = 1
    max_tries = 1
    job_timeout = 3600
    keep_result = 3600

    # arq reads this as an attribute, not a callable, so it is resolved when
    # the module is imported -- which for a worker entry point is boot.
    redis_settings = _redis_settings()
