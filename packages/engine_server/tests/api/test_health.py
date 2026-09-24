from __future__ import annotations

from pathlib import Path

import fakeredis
import pytest
import redis.asyncio as aioredis
from fastapi.testclient import TestClient

from engine import __version__
from engine.settings import Settings  # noqa: F401
from tests.conftest import build_client, make_settings


def test_health_is_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_health_does_not_probe_dependencies(tmp_path: Path) -> None:
    # A missing catalog and no Redis must not make /health fail, or a bad
    # dependency turns into a container restart loop.
    settings = make_settings(catalog_path=str(tmp_path / "absent"))
    unreachable = aioredis.from_url("redis://127.0.0.1:6390/0")
    client = build_client(settings, unreachable)  # No `with`: the lifespan would open the real Redis.
    assert client.get("/health").status_code == 200


def test_ready_when_every_dependency_is_up(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"catalog": "ok", "redis": "ok"}}


def test_ready_is_503_when_the_catalog_is_missing(tmp_path: Path) -> None:
    settings = make_settings(catalog_path=str(tmp_path / "absent"))
    client = build_client(settings, fakeredis.FakeServer())  # No `with`: the lifespan would open the real Redis.
    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "NOT_READY"
    assert body["details"]["checks"]["catalog"] == "catalog root does not exist"


def test_ready_is_503_when_redis_is_unreachable(settings: Settings) -> None:
    # The queue is not optional: without Redis a submitted job goes nowhere.
    unreachable = aioredis.from_url("redis://127.0.0.1:6390/0")
    client = build_client(settings, unreachable)  # No `with`: the lifespan would open the real Redis.
    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["details"]["checks"]["redis"] == "redis is unreachable"
    assert body["details"]["checks"]["catalog"] == "ok"


def test_ready_is_503_when_the_catalog_is_unreachable() -> None:
    # An unreachable object store raises rather than returning False; readiness
    # must answer no, and must not leak the backend's error text.
    settings = make_settings(catalog_path="s3://nonexistent-bucket-xyz/catalog")
    client = build_client(settings, fakeredis.FakeServer())  # No `with`: the lifespan would open the real Redis.
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["details"]["checks"]["catalog"] in {
        "catalog is unreachable",
        "catalog root does not exist",
    }


@pytest.mark.parametrize("route", ["/health", "/ready"])
def test_request_id_is_echoed(client: TestClient, route: str) -> None:
    response = client.get(route, headers={"x-request-id": "req_abc"})
    assert response.headers["x-request-id"] == "req_abc"


def test_request_id_is_generated_when_absent(client: TestClient) -> None:
    assert client.get("/health").headers["x-request-id"].startswith("req_")
