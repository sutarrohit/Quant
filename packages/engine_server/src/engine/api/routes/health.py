"""Liveness and readiness.

``/health`` answers "is this process up" and touches nothing, so a failing
dependency cannot make the container restart-loop.

``/ready`` answers "can this process do its job" and probes what the service
actually needs: the market-data catalog, and Redis for the job queue.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from engine import __version__
from engine.api.deps import JobStoreDep, SettingsDep
from engine.data.catalog import Catalog
from engine.errors import NotReadyError
from engine.settings import Settings
from engine.store.jobs import JobStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["meta"])


def check_catalog(settings: Settings) -> tuple[bool, str]:
    try:
        if Catalog.from_settings(settings).exists():
            return True, "ok"
    except Exception as exc:
        # The reason is logged, not returned: a readiness body is not the place
        # to leak a storage-backend error string.
        logger.warning("catalog probe failed", extra={"error": str(exc)})
        return False, "catalog is unreachable"
    return False, "catalog root does not exist"


async def check_redis(store: JobStore) -> tuple[bool, str]:
    return (True, "ok") if await store.ping() else (False, "redis is unreachable")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/ready")
async def ready(settings: SettingsDep, jobs: JobStoreDep) -> dict[str, Any]:
    catalog_ok, catalog_detail = check_catalog(settings)
    redis_ok, redis_detail = await check_redis(jobs)
    checks = {"catalog": catalog_detail, "redis": redis_detail}

    if not (catalog_ok and redis_ok):
        raise NotReadyError("service is not ready", details={"checks": checks})
    return {"status": "ready", "checks": checks}
