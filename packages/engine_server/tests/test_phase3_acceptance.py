"""Phase 3 acceptance (spec section 7.6).

Four criteria:

* submit, poll, and get a summary back, against real catalog data;
* a duplicate ``requestId`` returns the same ``jobId`` and does not run twice;
* an invalid spec is rejected in under 100 ms without touching the queue;
* a worker survives 50 sequential jobs inside an asserted memory ceiling.

The first and last run the real machinery -- real validation, a real claim, a
real child process, real Parquet. Only the arq daemon is absent: the task is
invoked directly, which is exactly what arq would do.
"""

from __future__ import annotations

import copy
import time
from pathlib import Path
from typing import Any

import fakeredis
import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient

from engine.settings import Settings
from engine.store.jobs import JobStore
from engine.types.jobs import JobStatus
from engine.worker.tasks import run_backtest
from tests.backtest.conftest import REQUEST
from tests.conftest import AUTH, RecordingQueue, build_client, make_settings

CATALOG = Path("catalog")

pytestmark = pytest.mark.skipif(
    not (CATALOG / "data" / "bar" / "BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL").exists(),
    reason="needs the Phase 0 catalog",
)


def rss_mb() -> float:
    """This process's resident set size, without a psutil dependency."""
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return 0.0


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(
        catalog_path="./catalog",
        artifact_path=str(tmp_path / "artifacts"),
        log_level="ERROR",
        backtest_timeout_seconds=120,
    )


@pytest.fixture
def redis_server() -> fakeredis.FakeServer:
    return fakeredis.FakeServer()


@pytest.fixture
def store(settings: Settings, redis_server: fakeredis.FakeServer) -> JobStore:
    return JobStore.from_settings(
        settings, fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True)
    )


@pytest.fixture
def queue() -> RecordingQueue:
    return RecordingQueue()


@pytest.fixture
def api(
    settings: Settings, redis_server: fakeredis.FakeServer, queue: RecordingQueue
) -> TestClient:
    return build_client(settings, redis_server, queue)


@pytest.fixture
def submission() -> dict[str, Any]:
    payload = copy.deepcopy(REQUEST)
    payload["start"] = "2024-01-01T00:00:00Z"
    payload["end"] = "2024-02-01T00:00:00Z"
    return payload


# --- submit, poll, result ------------------------------------------------


async def test_submit_poll_succeeded_with_a_summary(
    api: TestClient,
    store: JobStore,
    settings: Settings,
    submission: dict[str, Any],
    queue: RecordingQueue,
) -> None:
    accepted = api.post("/v1/backtests", json=submission, headers=AUTH)
    assert accepted.status_code == 202
    job_id = accepted.json()["jobId"]
    assert queue.enqueued == [job_id]

    # What the arq worker does when it picks the job up.
    assert await run_backtest({"job_store": store, "settings": settings}, job_id) == "succeeded"

    polled = api.get(f"/v1/backtests/{job_id}", headers=AUTH).json()

    assert polled["status"] == "SUCCEEDED"
    assert polled["startedAt"] and polled["finishedAt"]
    assert polled["error"] is None

    summary = polled["result"]["summary"]
    assert summary["tradeCount"] > 0
    assert float(summary["totalFees"]) > 0
    assert float(summary["totalSlippage"]) > 0
    for field in ("totalReturn", "cagr", "maxDrawdown", "sharpe", "sortino", "winRate"):
        assert field in summary


async def test_the_series_land_in_parquet_not_in_the_response(
    api: TestClient, store: JobStore, settings: Settings, submission: dict[str, Any]
) -> None:
    job_id = api.post("/v1/backtests", json=submission, headers=AUTH).json()["jobId"]
    await run_backtest({"job_store": store, "settings": settings}, job_id)

    result = api.get(f"/v1/backtests/{job_id}", headers=AUTH).json()["result"]

    assert "trades" not in result
    assert "equityCurve" not in result
    artifacts = result["artifacts"]
    assert Path(artifacts["trades"]).exists()
    assert Path(artifacts["equityCurve"]).exists()
    assert Path(artifacts["summary"]).exists()


async def test_a_result_is_not_published_when_api_control_is_unset(
    api: TestClient, store: JobStore, settings: Settings, submission: dict[str, Any]
) -> None:
    job_id = api.post("/v1/backtests", json=submission, headers=AUTH).json()["jobId"]
    await run_backtest({"job_store": store, "settings": settings}, job_id)
    assert api.get(f"/v1/backtests/{job_id}", headers=AUTH).json()["result"]["published"] is False


# --- idempotency ---------------------------------------------------------


async def test_a_duplicate_request_does_not_run_twice(
    api: TestClient,
    store: JobStore,
    settings: Settings,
    submission: dict[str, Any],
    queue: RecordingQueue,
) -> None:
    first = api.post("/v1/backtests", json=submission, headers=AUTH)
    job_id = first.json()["jobId"]
    ctx = {"job_store": store, "settings": settings}
    await run_backtest(ctx, job_id)
    finished = await store.require(job_id)

    second = api.post("/v1/backtests", json=submission, headers=AUTH)

    assert second.json()["jobId"] == job_id
    assert second.status_code == 200
    assert queue.enqueued == [job_id], "the work was queued a second time"

    # And the worker refuses to re-run a finished job even if it were.
    assert await run_backtest(ctx, job_id) == "succeeded"
    assert (await store.require(job_id)).finished_at == finished.finished_at


# --- fast rejection ------------------------------------------------------


def test_an_invalid_spec_is_rejected_fast_and_unqueued(
    api: TestClient, submission: dict[str, Any], queue: RecordingQueue
) -> None:
    submission["spec"]["exit"] = {"any": [{"type": "takeProfitPercent", "value": 4}]}
    api.post("/v1/backtests", json=submission, headers=AUTH)  # warm the catalog read

    worst = 0.0
    for index in range(5):
        submission["requestId"] = f"req_reject_{index}"
        started = time.perf_counter()
        response = api.post("/v1/backtests", json=submission, headers=AUTH)
        worst = max(worst, (time.perf_counter() - started) * 1000)
        assert response.status_code == 422

    assert worst < 100, f"slowest rejection took {worst:.1f} ms"
    assert queue.enqueued == []


# --- memory over many jobs ----------------------------------------------


@pytest.mark.slow
async def test_fifty_sequential_jobs_stay_within_a_memory_ceiling(
    store: JobStore, settings: Settings, submission: dict[str, Any]
) -> None:
    """Spec section 7.6.

    Nautilus engines hold a lot of memory, and a worker that ran them
    in-process would leak until it OOMs. Each backtest runs in a child process
    precisely so that memory returns when the child exits -- this measures
    whether it actually does, rather than assuming it.
    """
    # A one-week window: fifty real backtests, each with a real child process.
    submission["start"] = "2024-01-01T00:00:00Z"
    submission["end"] = "2024-01-08T00:00:00Z"
    ctx = {"job_store": store, "settings": settings}

    # One warm-up run so imports and caches are not counted as growth.
    submission["requestId"] = "req_warmup"
    record, _ = await store.claim("req_warmup", "hash_warmup", submission)
    assert await run_backtest(ctx, record.job_id) == "succeeded"

    baseline = rss_mb()
    samples: list[float] = []

    for index in range(50):
        payload = dict(submission, requestId=f"req_{index}")
        record, created = await store.claim(f"req_{index}", f"hash_{index}", payload)
        assert created
        assert await run_backtest(ctx, record.job_id) == "succeeded"
        samples.append(rss_mb())

    growth = samples[-1] - baseline
    assert growth < 100, (
        f"worker grew {growth:.0f} MB over 50 jobs "
        f"({baseline:.0f} -> {samples[-1]:.0f} MB); engines are leaking"
    )

    # And it must not be climbing steadily: a slow leak stays under a ceiling
    # for fifty jobs and takes the box down at five hundred.
    first_half = sum(samples[:25]) / 25
    second_half = sum(samples[25:]) / 25
    assert second_half - first_half < 50, (
        f"RSS trended upward: {first_half:.0f} MB -> {second_half:.0f} MB"
    )


@pytest.mark.slow
async def test_fifty_jobs_all_reach_a_terminal_status(
    store: JobStore, settings: Settings, submission: dict[str, Any]
) -> None:
    # A job stuck RUNNING is worse than one that failed: a caller polls forever
    # and the slot never frees.
    submission["start"] = "2024-01-01T00:00:00Z"
    submission["end"] = "2024-01-08T00:00:00Z"
    ctx = {"job_store": store, "settings": settings}

    job_ids = []
    for index in range(50):
        payload = dict(submission, requestId=f"req_t{index}")
        record, _ = await store.claim(f"req_t{index}", f"hash_t{index}", payload)
        job_ids.append(record.job_id)
        await run_backtest(ctx, record.job_id)

    statuses = [(await store.require(job_id)).status for job_id in job_ids]
    assert all(status is JobStatus.SUCCEEDED for status in statuses)
    assert len(set(job_ids)) == 50
