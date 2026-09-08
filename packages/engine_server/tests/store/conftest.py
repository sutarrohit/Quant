"""Job store fixtures.

Every test runs against **both** fakeredis and a real Redis when one is
reachable. Atomicity is the whole point of this module, and a fake that
silently differs from Redis would let a broken claim pass.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from itertools import count

import pytest
import redis.asyncio as aioredis

REAL_REDIS_URL = os.environ.get("NT_TEST_REDIS_URL", "redis://localhost:6379/15")


async def _real_redis_available() -> bool:
    try:
        client = aioredis.from_url(REAL_REDIS_URL, decode_responses=True)
        await client.ping()
        await client.aclose()
        return True
    except Exception:
        return False


@pytest.fixture(params=["fake", "real"])
async def redis_client(request: pytest.FixtureRequest) -> AsyncIterator[aioredis.Redis]:
    if request.param == "fake":
        import fakeredis.aioredis

        client = fakeredis.aioredis.FakeRedis(decode_responses=True)
        yield client
        await client.aclose()
        return

    if not await _real_redis_available():
        pytest.skip(f"no Redis at {REAL_REDIS_URL}")
    client = aioredis.from_url(REAL_REDIS_URL, decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
def clock() -> Clock:
    return Clock()


class Clock:
    """A clock that advances only when told, so timestamps are assertable."""

    def __init__(self) -> None:
        self.moment = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, seconds: int) -> None:
        self.moment += timedelta(seconds=seconds)


@pytest.fixture
def job_ids() -> IdFactory:
    return IdFactory()


class IdFactory:
    def __init__(self) -> None:
        self._counter = count(1)

    def __call__(self) -> str:
        return f"job_{next(self._counter):04d}"


@pytest.fixture
def store(redis_client: aioredis.Redis, clock: Clock, job_ids: IdFactory) -> object:
    from engine.store.jobs import JobStore

    return JobStore(redis_client, ttl_seconds=3600, now=clock, new_job_id=job_ids)
