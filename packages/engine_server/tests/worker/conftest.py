"""Worker fixtures."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import fakeredis
import fakeredis.aioredis
import pytest

from engine.data.provision import ProvisionResult
from engine.settings import Settings
from engine.store.jobs import JobStore
from engine.worker import tasks
from tests.backtest.conftest import REQUEST

CATALOG = Path("catalog")

requires_catalog = pytest.mark.skipif(
    not (CATALOG / "data" / "bar" / "BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL").exists(),
    reason="needs the Phase 0 catalog",
)


@pytest.fixture
def worker_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        catalog_path="./catalog",
        artifact_path=str(tmp_path / "artifacts"),
        internal_api_key="test-token",
        log_level="ERROR",
        backtest_timeout_seconds=120,
    )


@pytest.fixture
def store(worker_settings: Settings) -> JobStore:
    redis = fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    return JobStore.from_settings(worker_settings, redis)


@pytest.fixture
def ctx(store: JobStore, worker_settings: Settings) -> dict[str, Any]:
    return {"job_store": store, "settings": worker_settings}


@pytest.fixture(autouse=True)
def no_venue_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let a unit test reach a venue.

    `run_backtest` provisions missing data before running, and these settings
    point at the real `./catalog` -- so without this the suite quietly downloads
    a month of bars from Binance the first time it runs, which is both a network
    dependency and a mutation of the developer's catalog.

    A test that wants the provisioning path patches `ensure_window` itself; a
    later `setattr` wins over this one.
    """
    monkeypatch.setattr(
        tasks,
        "ensure_window",
        lambda **kwargs: ProvisionResult(kwargs["bar_type"], fetched=False, bars_written=0),
    )


@pytest.fixture
def submission() -> dict[str, Any]:
    payload = copy.deepcopy(REQUEST)
    payload["start"] = "2024-01-01T00:00:00Z"
    payload["end"] = "2024-02-01T00:00:00Z"
    return payload
