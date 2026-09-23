from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

import pytest

from engine.data.provision import ProvisionResult
from engine.errors import BacktestFailed, BacktestTimeout, DataRangeUnavailable, SymbolUnknownAtVenue
from engine.store.jobs import JobStore
from engine.types.jobs import JobStatus
from engine.worker import tasks
from engine.worker.tasks import run_backtest
from tests.worker.conftest import requires_catalog


def stub_result(**overrides: Any) -> dict[str, Any]:
    """A result shaped the way the runner returns one."""
    return {
        "fills": 4,
        "positions": 2,
        "closedPositions": 2,
        "realizedPnl": "100",
        "totalCommission": "12",
        "summary": {"totalReturn": "1.0"},
        "trades": [],
        "equityCurve": [],
        **overrides,
    }


async def claim(store: JobStore, submission: dict[str, Any]) -> str:
    record, _ = await store.claim("req_1", "hash_a", submission)
    return record.job_id


# --- the happy path ------------------------------------------------------


async def test_a_job_runs_to_succeeded(
    ctx: dict[str, Any], store: JobStore, submission: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "run_isolated", lambda *a, **k: stub_result())
    job_id = await claim(store, submission)

    assert await run_backtest(ctx, job_id) == "succeeded"

    record = await store.require(job_id)
    assert record.status is JobStatus.SUCCEEDED
    assert record.result is not None
    assert record.result["fills"] == 4
    assert record.result["summary"] == {"totalReturn": "1.0"}
    # The series are referenced, never inlined (spec section 7.5).
    assert "trades" not in record.result
    assert "artifacts" in record.result
    assert record.started_at is not None
    assert record.finished_at is not None
    assert record.error is None


# --- data provisioning (ADR-003) -----------------------------------------


async def test_data_is_provisioned_before_the_run(
    ctx: dict[str, Any], store: JobStore, submission: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The catalog is filled first, and the job says so while it happens."""
    seen: list[str] = []

    def provision(**kwargs: Any) -> ProvisionResult:
        seen.append("provision")
        return ProvisionResult(kwargs["bar_type"], fetched=True, bars_written=96)

    def run(*args: object, **kwargs: object) -> dict[str, Any]:
        seen.append("run")
        return stub_result()

    monkeypatch.setattr(tasks, "ensure_window", provision)
    monkeypatch.setattr(tasks, "run_isolated", run)
    job_id = await claim(store, submission)

    assert await run_backtest(ctx, job_id) == "succeeded"
    # Order is the whole point: a run that starts before its data is there
    # fails with NO_DATA_FOR_WINDOW for no reason.
    assert seen == ["provision", "run"]


async def test_the_job_is_visibly_fetching_while_it_fetches(
    ctx: dict[str, Any], store: JobStore, submission: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A caller polling a cold two-year window waits minutes. FETCHING_DATA is
    # how they learn it is downloading history rather than wedged.
    observed: list[JobStatus] = []
    job_id = await claim(store, submission)

    def provision(**kwargs: Any) -> ProvisionResult:
        record = asyncio.run_coroutine_threadsafe(store.get(job_id), loop).result()
        observed.append(record.status)
        return ProvisionResult(kwargs["bar_type"], fetched=True, bars_written=1)

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(tasks, "ensure_window", provision)
    monkeypatch.setattr(tasks, "run_isolated", lambda *a, **k: stub_result())

    await run_backtest(ctx, job_id)

    assert observed == [JobStatus.FETCHING_DATA]


async def test_a_symbol_the_venue_does_not_list_fails_the_job(
    ctx: dict[str, Any], store: JobStore, submission: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def unknown(**kwargs: object) -> ProvisionResult:
        raise SymbolUnknownAtVenue("NOTACOIN is not listed on Binance spot")

    monkeypatch.setattr(tasks, "ensure_window", unknown)
    job_id = await claim(store, submission)

    assert await run_backtest(ctx, job_id) == "failed"

    record = await store.require(job_id)
    assert record.status is JobStatus.FAILED
    assert record.error is not None
    # A code the TypeScript caller can branch on, not prose.
    assert record.error["code"] == "SYMBOL_UNKNOWN_AT_VENUE"


async def test_a_window_the_venue_cannot_cover_fails_the_job(
    ctx: dict[str, Any], store: JobStore, submission: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def short(**kwargs: object) -> ProvisionResult:
        raise DataRangeUnavailable("SOLUSDT.BINANCE has no data before 2020-08-11")

    monkeypatch.setattr(tasks, "ensure_window", short)
    job_id = await claim(store, submission)

    assert await run_backtest(ctx, job_id) == "failed"
    record = await store.require(job_id)
    assert record.error is not None
    assert record.error["code"] == "DATA_RANGE_UNAVAILABLE"


async def test_a_backtest_never_runs_on_a_window_that_could_not_be_filled(
    ctx: dict[str, Any], store: JobStore, submission: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure mode worth a test of its own.

    Provisioning failing and the run proceeding anyway would produce a result
    over whatever subset happened to be on disk -- a number that looks like an
    answer to the question that was asked, and is not.
    """
    ran = False

    def never(*args: object, **kwargs: object) -> dict[str, Any]:
        nonlocal ran
        ran = True
        return stub_result()

    def fails(**kwargs: object) -> ProvisionResult:
        raise DataRangeUnavailable("no data for that window")

    monkeypatch.setattr(tasks, "ensure_window", fails)
    monkeypatch.setattr(tasks, "run_isolated", never)
    job_id = await claim(store, submission)

    await run_backtest(ctx, job_id)

    assert not ran


# --- failures ------------------------------------------------------------


async def test_a_timeout_is_recorded_with_its_code(
    ctx: dict[str, Any], store: JobStore, submission: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(*args: object, **kwargs: object) -> None:
        raise BacktestTimeout("backtest exceeded 900s")

    monkeypatch.setattr(tasks, "run_isolated", timeout)
    job_id = await claim(store, submission)

    assert await run_backtest(ctx, job_id) == "timeout"

    record = await store.require(job_id)
    assert record.status is JobStatus.FAILED
    assert record.error == {"code": "TIMEOUT", "message": "backtest exceeded 900s"}


async def test_a_failure_records_a_code_never_a_traceback(
    ctx: dict[str, Any],
    store: JobStore,
    submission: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Spec section 7.4: the traceback is logged and never leaked to a caller.
    def boom(*args: object, **kwargs: object) -> None:
        raise BacktestFailed("ValueError: instrument not found in cache")

    monkeypatch.setattr(tasks, "run_isolated", boom)
    job_id = await claim(store, submission)

    with caplog.at_level(logging.ERROR):
        assert await run_backtest(ctx, job_id) == "failed"

    record = await store.require(job_id)
    assert record.status is JobStatus.FAILED
    assert record.error is not None
    assert record.error["code"] == "BACKTEST_FAILED"
    assert "Traceback" not in record.to_json()
    assert any("backtest failed" in message for message in caplog.messages)


async def test_an_unexpected_error_still_terminates_the_job(
    ctx: dict[str, Any], store: JobStore, submission: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A job left RUNNING forever is worse than a job marked failed: a caller
    # polls indefinitely and a worker slot never frees.
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("something nobody predicted")

    monkeypatch.setattr(tasks, "run_isolated", boom)
    job_id = await claim(store, submission)

    assert await run_backtest(ctx, job_id) == "failed"
    assert (await store.require(job_id)).error == {
        "code": "INTERNAL",
        "message": "RuntimeError",
    }


async def test_an_unreadable_stored_request_fails_the_job(ctx: dict[str, Any], store: JobStore) -> None:
    record, _ = await store.claim("req_1", "hash_a", {"not": "a request"})

    assert await run_backtest(ctx, record.job_id) == "failed"
    assert (await store.require(record.job_id)).status is JobStatus.FAILED


# --- races ---------------------------------------------------------------


async def test_a_cancelled_job_is_not_run(
    ctx: dict[str, Any], store: JobStore, submission: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Cancellation races the worker picking the job up. mark_running is
    # compare-and-set, so the worker must notice it lost.
    ran = []
    monkeypatch.setattr(tasks, "run_isolated", lambda *a, **k: ran.append(1) or stub_result())
    job_id = await claim(store, submission)
    await store.cancel(job_id)

    assert await run_backtest(ctx, job_id) == "cancelled"

    assert ran == []
    assert (await store.require(job_id)).status is JobStatus.CANCELLED


async def test_an_already_finished_job_is_not_rerun(
    ctx: dict[str, Any], store: JobStore, submission: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = []
    monkeypatch.setattr(tasks, "run_isolated", lambda *a, **k: ran.append(1) or stub_result())
    job_id = await claim(store, submission)
    await store.mark_running(job_id)
    await store.mark_succeeded(job_id, {"fills": 1})

    await run_backtest(ctx, job_id)

    assert ran == []
    assert (await store.require(job_id)).result == {"fills": 1}


async def test_a_missing_job_is_not_an_error(ctx: dict[str, Any]) -> None:
    # The record's TTL can outlive the queue entry. Nothing to run, nothing to
    # fail, and the worker must not crash.
    assert await run_backtest(ctx, "job_nope") == "missing"


# --- end to end ----------------------------------------------------------


@requires_catalog
async def test_a_real_backtest_runs_through_the_task(
    ctx: dict[str, Any], store: JobStore, submission: dict[str, Any]
) -> None:
    """No stubs: a real request, a real child process, a real result."""
    job_id = await claim(store, submission)

    assert await run_backtest(ctx, job_id) == "succeeded"

    record = await store.require(job_id)
    assert record.status is JobStatus.SUCCEEDED
    assert record.result is not None
    assert record.result["fills"] > 0
    assert record.result["closedPositions"] > 0
    assert Decimal(record.result["totalCommission"]) > 0


async def test_artifacts_are_written_and_referenced(
    ctx: dict[str, Any],
    store: JobStore,
    submission: dict[str, Any],
    worker_settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlib import Path

    monkeypatch.setattr(
        tasks,
        "run_isolated",
        lambda *a, **k: stub_result(
            trades=[{"pnl": "100", "side": "BUY"}],
            equityCurve=[{"time": "2024-01-01T00:00:00+00:00", "equity": "10100", "drawdown": "0"}],
        ),
    )
    job_id = await claim(store, submission)

    await run_backtest(ctx, job_id)

    result = (await store.require(job_id)).result
    assert result is not None
    artifacts = result["artifacts"]
    assert Path(artifacts["summary"]).exists()
    assert Path(artifacts["trades"]).exists()
    assert Path(artifacts["equityCurve"]).exists()


async def test_a_failure_to_persist_does_not_fail_the_job(
    ctx: dict[str, Any],
    store: JobStore,
    submission: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The numbers are already computed. Losing the series is recoverable by
    # re-running; losing the run is not.
    monkeypatch.setattr(tasks, "run_isolated", lambda *a, **k: stub_result())

    def broken(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(tasks.ArtifactStore, "write_rows", broken)
    job_id = await claim(store, submission)

    assert await run_backtest(ctx, job_id) == "succeeded"

    record = await store.require(job_id)
    assert record.status is JobStatus.SUCCEEDED
    assert record.result is not None
    assert record.result["artifacts"] == {}
