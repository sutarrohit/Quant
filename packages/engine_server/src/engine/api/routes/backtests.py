"""Backtest submission and status (spec section 7.2).

**This module never runs a backtest.** It validates synchronously so a caller
gets fast feedback on a bad spec, then enqueues. A backtest pins a CPU for
minutes; running one here would block the event loop and take the service down
under two concurrent users (spec section 7.1).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import ValidationError

from engine.api.auth import InternalAuth
from engine.api.deps import JobStoreDep, SettingsDep
from engine.backtest.queue import JobQueue
from engine.backtest.request import BacktestRequest
from engine.data.catalog import Catalog
from engine.data.timeframes import Timeframe
from engine.dsl.schema import StrategySpec
from engine.dsl.validator import SpecError, SpecErrorCode, validate_spec
from engine.errors import SpecInvalid
from engine.logging import log_context
from engine.store.jobs import JobRecord

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/backtests", tags=["backtests"], dependencies=[InternalAuth])


async def get_queue(request: Request) -> JobQueue:
    queue: JobQueue = request.app.state.queue
    return queue


QueueDep = Annotated[JobQueue, Depends(get_queue)]


def available_bars(request: BacktestRequest, timeframe: Timeframe) -> int:
    """Bars the requested window can contain.

    Computed from the window rather than read from the catalog: this runs on
    the request path, and an indicator needing more warmup than the window
    holds is wrong regardless of what has been ingested.
    """
    span = (request.end - request.start).total_seconds()
    return int(span // timeframe.duration.total_seconds())


def parse_spec(payload: dict[str, Any]) -> StrategySpec:
    try:
        return StrategySpec.model_validate(payload)
    except ValidationError as exc:
        # Schema failures are reshaped into the same {"errors": [...]} envelope
        # as semantic ones, so the caller has one thing to render.
        raise SpecInvalid(
            [
                SpecError(
                    path="spec." + ".".join(str(part) for part in error["loc"]),
                    code=SpecErrorCode.UNKNOWN_INDICATOR
                    if "indicator" in str(error["loc"])
                    else SpecErrorCode.UNSUPPORTED_OPERATOR,
                    message=error["msg"],
                ).model_dump(mode="json")
                for error in exc.errors()
            ]
        ) from exc


def job_response(record: JobRecord) -> dict[str, Any]:
    return {
        "jobId": record.job_id,
        "status": record.status.value,
        "submittedAt": record.submitted_at.isoformat(),
        "startedAt": record.started_at.isoformat() if record.started_at else None,
        "finishedAt": record.finished_at.isoformat() if record.finished_at else None,
        "error": record.error,
        "result": record.result,
    }


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def submit(
    payload: BacktestRequest,
    settings: SettingsDep,
    jobs: JobStoreDep,
    queue: QueueDep,
    response: Response,
) -> dict[str, Any]:
    spec = parse_spec(payload.spec)

    catalog = Catalog.from_settings(settings)
    errors = validate_spec(
        spec,
        available_bars=available_bars(payload, spec.market.timeframe),
        known_instruments=catalog.backtestable_instrument_ids(),
    )
    if errors:
        # Rejected before the queue is touched: a bad spec costs the caller a
        # round trip, not a worker slot.
        raise SpecInvalid([error.model_dump(mode="json") for error in errors])

    record, created = await jobs.claim(
        payload.request_id,
        payload.payload_hash(),
        payload.model_dump(mode="json", by_alias=True),
    )

    with log_context(job_id=record.job_id, request_id=payload.request_id):
        if created:
            await queue.enqueue(record.job_id)
            logger.info("backtest enqueued", extra={"spec_hash": record.payload_hash})
        else:
            # Idempotent replay: the existing job, never a second run.
            logger.info("duplicate request returned existing job")
            response.status_code = status.HTTP_200_OK

    return {"jobId": record.job_id, "status": record.status.value}


@router.get("/{job_id}")
async def get_job(job_id: str, jobs: JobStoreDep) -> dict[str, Any]:
    return job_response(await jobs.require(job_id))


@router.delete("/{job_id}")
async def cancel_job(job_id: str, jobs: JobStoreDep) -> dict[str, Any]:
    return job_response(await jobs.cancel(job_id))
