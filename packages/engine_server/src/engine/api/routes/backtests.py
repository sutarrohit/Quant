"""Backtest submission and status (spec section 7.2).

**This module never runs a backtest.** It validates synchronously so a caller
gets fast feedback on a bad spec, then enqueues. A backtest pins a CPU for
minutes; running one here would block the event loop and take the service down
under two concurrent users (spec section 7.1).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import ValidationError

from engine.api.auth import InternalAuth
from engine.api.deps import JobStoreDep, RedisDep, SettingsDep
from engine.backtest.queue import JobQueue
from engine.data.availability import SymbolAvailability
from engine.data.catalog import Catalog
from engine.data.timeframes import Timeframe
from engine.dsl.validator import validate_spec
from engine.errors import JobNotFound, NotFoundError, SpecInvalid
from engine.logging import log_context
from engine.store.artifacts import SERIES_FILES, ArtifactStore
from engine.types.backtest import BacktestRequest
from engine.types.dsl import StrategySpec
from engine.types.jobs import JobRecord
from engine.types.spec_errors import SpecError, SpecErrorCode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/backtests", tags=["backtests"], dependencies=[InternalAuth])

#: Exactly what ``store.jobs._new_job_id`` mints. ``job_id`` becomes a
#: directory, and "../.." is a valid string.
JOB_ID = re.compile(r"^job_[0-9a-f]{32}$")

#: Whole for a typical trade table, not for a 50,000-point curve.
DEFAULT_LIMIT: Final = 1_000
MAX_LIMIT: Final = 10_000


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
    redis: RedisDep,
    response: Response,
) -> dict[str, Any]:
    spec = parse_spec(payload.spec)

    # Knowable, not "already ingested": the worker fetches what the catalog is
    # missing, so a symbol the venue lists is a valid request even on a cold
    # catalog. Only a symbol nobody can produce data for is a spec error.
    availability = SymbolAvailability(Catalog.from_settings(settings), settings, redis)
    errors = validate_spec(
        spec,
        available_bars=available_bars(payload, spec.market.timeframe),
        known_instruments=await availability.knowable(spec.market.instrument_ids),
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


@router.get("/{job_id}/artifacts/{name}")
async def get_artifact(
    job_id: str,
    name: str,
    settings: SettingsDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """One page of a finished run's equity curve or trade table.

    The job record carries the summary; these are the series behind it, held as
    Parquet rather than inlined (spec section 7.5). This is how a caller asks.

    **Both path segments are validated before anything is opened** -- between
    them they name a directory and a file.

    Not gated on the job record: records expire after ``NT_JOB_TTL_SECONDS``
    and the artifacts do not.
    """
    if name not in SERIES_FILES:  # First: an unknown name must not cost a round trip.
        raise NotFoundError(
            f"unknown artifact {name!r}", details={"known": sorted(SERIES_FILES)}
        )
    if not JOB_ID.fullmatch(job_id):
        raise JobNotFound(f"no such job {job_id!r}")

    store = ArtifactStore.from_settings(settings)

    # fsspec blocks, and against S3 on the network -- in an async handler that
    # stalls every other request. Hence the thread.
    if not await asyncio.to_thread(store.job_exists, job_id):
        raise JobNotFound(f"no artifacts for job {job_id}")

    rows, total = await asyncio.to_thread(
        store.read_series, job_id, name, offset=offset, limit=limit
    )
    return {"rows": rows, "total": total, "offset": offset, "limit": limit}
