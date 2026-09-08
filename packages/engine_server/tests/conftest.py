"""Shared fixtures.

Settings are built explicitly with ``_env_file=None`` so no test ever depends on
a developer's local .env.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import fakeredis
import fakeredis.aioredis
import pytest
import redis.asyncio as aioredis
from fastapi.testclient import TestClient

from engine.api.app import create_app
from engine.api.deps import get_redis
from engine.api.routes.backtests import get_queue
from engine.settings import Settings, get_settings

TOKEN = "test-internal-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def make_settings(**overrides: object) -> Settings:
    """Settings with a token already set.

    create_app refuses to start without one, so every test that builds an
    app needs it. Centralised here rather than repeated.
    """
    return Settings(_env_file=None, internal_api_key=TOKEN, **overrides)  # type: ignore[arg-type]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    return Settings(
        _env_file=None,
        catalog_path=str(catalog),
        raw_path=str(tmp_path / "raw"),
        artifact_path=str(tmp_path / "artifacts"),
        internal_api_key=TOKEN,
    )


@pytest.fixture
def redis_server() -> fakeredis.FakeServer:
    """Shared fake Redis *state*.

    TestClient runs every request in a fresh event loop, and an asyncio Redis
    client is bound to the loop that created it. Sharing the server and making
    a client per call keeps the data while staying loop-safe.
    """
    return fakeredis.FakeServer()


@pytest.fixture
def fake_redis(redis_server: fakeredis.FakeServer) -> aioredis.Redis:
    return fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True)


class RecordingQueue:
    """A queue that records what was enqueued instead of running it.

    The API's contract is that it enqueues and returns; whether a worker ever
    picks the job up is Step 15's business.
    """

    def __init__(self) -> None:
        self.enqueued: list[str] = []

    async def enqueue(self, job_id: str) -> None:
        self.enqueued.append(job_id)

    async def close(self) -> None:
        pass


@pytest.fixture
def queue() -> RecordingQueue:
    return RecordingQueue()


def build_client(
    settings: Settings,
    redis: aioredis.Redis | fakeredis.FakeServer | None = None,
    queue: object | None = None,
) -> TestClient:
    """A TestClient wired to test doubles.

    Built without entering the lifespan, so no test opens a real Redis
    connection; the dependencies the lifespan would provide are overridden
    instead. Production wiring is untouched.

    Passing a ``FakeServer`` yields a fresh client per request bound to the
    calling loop; passing a client uses it as-is, which is what the
    unreachable-Redis tests want.
    """
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings

    if isinstance(redis, fakeredis.FakeServer):
        app.dependency_overrides[get_redis] = lambda: fakeredis.aioredis.FakeRedis(
            server=redis, decode_responses=True
        )
    elif redis is not None:
        app.dependency_overrides[get_redis] = lambda: redis

    if queue is not None:
        app.dependency_overrides[get_queue] = lambda: queue
    return TestClient(app)


@pytest.fixture
def client(
    settings: Settings, redis_server: fakeredis.FakeServer, queue: RecordingQueue
) -> Iterator[TestClient]:
    yield build_client(settings, redis_server, queue)
