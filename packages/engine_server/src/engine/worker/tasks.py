"""The backtest task (spec section 7.4).

One job, one fresh process, one terminal status. The task itself stays on the
event loop and does no heavy work: the run happens in a child process, so arq
keeps its heartbeat and the worker stays cancellable.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from engine.backtest.request import BacktestRequest
from engine.backtest.runner import BacktestFailed, BacktestTimeout, run_isolated
from engine.errors import EngineError, ErrorCode
from engine.logging import log_context
from engine.settings import Settings
from engine.store.artifacts import ArtifactStore
from engine.store.jobs import JobStatus, JobStore
from engine.store.publish import publish_result

logger = logging.getLogger(__name__)


async def run_backtest(ctx: dict[str, Any], job_id: str) -> str:
    """Execute one queued backtest.

    Returns a short status string for arq's own bookkeeping; the job record is
    the answer a caller reads.
    """
    store: JobStore = ctx["job_store"]
    settings: Settings = ctx["settings"]

    record = await store.get(job_id)
    if record is None:
        # The record expired, or the id was never real. Nothing to run and
        # nothing to fail.
        logger.warning("job not found", extra={"job_id": job_id})
        return "missing"

    with log_context(job_id=job_id, request_id=record.request_id):
        claimed = await store.mark_running(job_id)
        if claimed.status is not JobStatus.RUNNING:
            # Cancelled between enqueue and pickup, or already finished. The
            # transition is compare-and-set, so this is the losing side of that
            # race and must not run.
            logger.info("job not runnable", extra={"status": claimed.status.value})
            return claimed.status.value.lower()

        try:
            request = BacktestRequest.model_validate(record.request)
        except Exception as exc:
            # A stored request that no longer parses is a bug, not a user
            # error, but it still has to end the job rather than hang it.
            logger.exception("stored request is unreadable")
            await store.mark_failed(job_id, ErrorCode.REQUEST_INVALID.value, str(exc)[:200])
            return "failed"

        logger.info("backtest started")
        try:
            result = await asyncio.to_thread(run_isolated, request, settings)
        except BacktestTimeout as exc:
            logger.warning("backtest timed out", extra={"code": exc.code.value})
            await store.mark_failed(job_id, exc.code.value, exc.message)
            return "timeout"
        except (BacktestFailed, EngineError) as exc:
            # The traceback was logged by the runner; only a code and a short
            # message reach the job record (spec section 7.4).
            logger.error("backtest failed", extra={"code": exc.code.value})
            await store.mark_failed(job_id, exc.code.value, exc.message)
            return "failed"
        except Exception as exc:  # noqa: BLE001 -- a job must always terminate
            logger.exception("unexpected worker failure")
            await store.mark_failed(job_id, ErrorCode.INTERNAL.value, type(exc).__name__)
            return "failed"

        artifacts = _persist(job_id, result, settings)
        published = await asyncio.to_thread(
            publish_result, job_id, {"summary": result["summary"], "artifacts": artifacts}, settings
        )
        # The job record keeps the summary and pointers. The series stay in
        # Parquet: a caller polling for a status should not receive a megabyte
        # of equity curve it did not ask for (spec section 7.5).
        await store.mark_succeeded(
            job_id,
            {
                "fills": result["fills"],
                "positions": result["positions"],
                "closedPositions": result["closedPositions"],
                "realizedPnl": result["realizedPnl"],
                "totalCommission": result["totalCommission"],
                "summary": result["summary"],
                "artifacts": artifacts,
                "published": published,
            },
        )
        logger.info("backtest succeeded", extra={"fills": result.get("fills")})
        return "succeeded"


def _persist(job_id: str, result: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Write the series and return references to them.

    A failure to persist must not turn a completed backtest into a failed job.
    The numbers are already computed and stored on the record; losing the
    series is recoverable by re-running, whereas losing the run is not.
    """
    try:
        artifacts = ArtifactStore.from_settings(settings).write_rows(
            job_id,
            summary=result["summary"],
            trades=result["trades"],
            equity_curve=result["equityCurve"],
        )
        return artifacts.to_dict()
    except Exception:
        logger.exception("could not persist artifacts", extra={"job_id": job_id})
        return {}
