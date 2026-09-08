"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, Request

from engine.settings import Settings, get_settings
from engine.store.jobs import JobStore

SettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_redis(request: Request) -> AsyncIterator[aioredis.Redis]:
    """The app's shared Redis client.

    One pool for the process, created at startup: a client per request would
    open a connection per request and exhaust the server under load.
    """
    yield request.app.state.redis


RedisDep = Annotated[aioredis.Redis, Depends(get_redis)]


async def get_job_store(settings: SettingsDep, redis: RedisDep) -> JobStore:
    return JobStore.from_settings(settings, redis)


JobStoreDep = Annotated[JobStore, Depends(get_job_store)]
