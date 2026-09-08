"""Backtest job records and idempotency (spec sections 7.2, 9).

``requestId`` is the idempotency key. A repeat submission returns the existing
job and never starts a second run; the same ``requestId`` carrying a *different*
payload is a conflict, because the caller has reused an identifier for two
different pieces of work and silently returning either answer would be wrong.

**The claim is atomic.** Two concurrent submissions of the same ``requestId``
must produce exactly one job. Read-then-write cannot promise that: both callers
read "absent" and both create. The claim here writes a candidate record, then
takes the idempotency pointer with ``SET NX``; whichever caller loses deletes
its candidate and reads the winner's. One round trip, no lock, no polling.

Status transitions are compare-and-set in Lua for the same reason. Cancelling
races the worker picking the job up, and "cancel only if still QUEUED" has to
be decided inside Redis rather than between two calls.

Nothing here is the financial record. It is job bookkeeping with a TTL.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict
from redis.asyncio import Redis

from engine.errors import EngineError, ErrorCode
from engine.settings import Settings

JOB_KEY = "job:{job_id}"
IDEMPOTENCY_KEY = "idem:{request_id}"

# Set the given fields only if the status is currently one of the allowed
# values, and return the status actually stored.
#
# The record is a hash and this script touches only the fields it is given.
# An earlier version decoded the whole record, patched it, and re-encoded --
# which quietly corrupted it: Lua has one table type, so cjson encodes an
# empty object as `[]`, turning a stored `{}` into a list on every transition.
_TRANSITION = """
local status = redis.call('HGET', KEYS[1], 'status')
if not status then return nil end
for _, allowed in ipairs(cjson.decode(ARGV[2])) do
  if status == allowed then
    redis.call('HSET', KEYS[1], unpack(cjson.decode(ARGV[1])))
    return redis.call('HGET', KEYS[1], 'status')
  end
end
return status
"""

#: Record fields held as JSON inside the hash. Everything else is a plain
#: string, so a human reading Redis can see what a job is doing.
_JSON_FIELDS = ("request", "error", "result")


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def terminal(self) -> bool:
        return self in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)


class RequestIdConflict(EngineError):
    """The same requestId was submitted with a different payload."""

    code = ErrorCode.REQUEST_ID_CONFLICT
    http_status = 409


class JobNotFound(EngineError):
    code = ErrorCode.JOB_NOT_FOUND
    http_status = 404


class JobNotCancellable(EngineError):
    """Already running or finished. Cancelling would be a lie."""

    code = ErrorCode.JOB_NOT_CANCELLABLE
    http_status = 409


class JobRecord(BaseModel):
    model_config = ConfigDict(frozen=True, use_enum_values=False)

    job_id: str
    request_id: str
    payload_hash: str
    #: The submission itself. The worker loads the job by id and needs
    #: everything required to run it; carrying it here means the queue moves
    #: only an identifier and a replay reads the same bytes the first attempt did.
    request: dict[str, Any]
    status: JobStatus
    submitted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    #: Machine-readable failure, never a traceback (spec section 7.4).
    error: dict[str, Any] | None = None
    result: dict[str, Any] | None = None

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str) -> Self:
        return cls.model_validate_json(raw)


def _now() -> datetime:
    return datetime.now(UTC)


def _new_job_id() -> str:
    return f"job_{uuid.uuid4().hex}"


class JobStore:
    def __init__(
        self,
        redis: Redis,
        *,
        ttl_seconds: int = 7 * 24 * 3600,
        now: Callable[[], datetime] = _now,
        new_job_id: Callable[[], str] = _new_job_id,
    ) -> None:
        self._redis = redis
        self._ttl = ttl_seconds
        self._now = now
        self._new_job_id = new_job_id
        self._transition = redis.register_script(_TRANSITION)

    @classmethod
    def from_settings(cls, settings: Settings, redis: Redis) -> Self:
        return cls(redis, ttl_seconds=settings.job_ttl_seconds)

    async def ping(self) -> bool:
        """Backs the Redis half of ``GET /ready``."""
        try:
            return bool(await self._redis.ping())
        except Exception:
            return False

    # --- claiming --------------------------------------------------------

    async def claim(
        self, request_id: str, payload_hash: str, request: dict[str, Any]
    ) -> tuple[JobRecord, bool]:
        """Get or create the job for a ``requestId``.

        Returns ``(record, created)``. ``created`` is False when this
        ``requestId`` had already been claimed, which is the idempotent path.
        Raises ``RequestIdConflict`` when the stored payload differs.
        """
        candidate = JobRecord(
            job_id=self._new_job_id(),
            request_id=request_id,
            payload_hash=payload_hash,
            request=request,
            status=JobStatus.QUEUED,
            submitted_at=self._now(),
        )

        # Write the record before taking the pointer, so a caller that reads
        # the pointer always finds a record behind it.
        await self._write(candidate)
        won = await self._redis.set(
            IDEMPOTENCY_KEY.format(request_id=request_id),
            candidate.job_id,
            nx=True,
            ex=self._ttl,
        )
        if won:
            return candidate, True

        await self._redis.delete(JOB_KEY.format(job_id=candidate.job_id))
        existing = await self._existing_for(request_id)
        if existing.payload_hash != payload_hash:
            raise RequestIdConflict(
                f"requestId {request_id!r} was already submitted with a different payload",
                details={"jobId": existing.job_id},
            )
        return existing, False

    async def _existing_for(self, request_id: str) -> JobRecord:
        job_id = await self._redis.get(IDEMPOTENCY_KEY.format(request_id=request_id))
        if job_id is None:
            # The pointer expired between the failed SET NX and this read.
            raise JobNotFound(f"no job for requestId {request_id!r}")
        return await self.require(_decode(job_id))

    # --- reading ---------------------------------------------------------

    async def get(self, job_id: str) -> JobRecord | None:
        # redis-py types hgetall as sync-or-async; it is async on this client.
        fields = await self._redis.hgetall(JOB_KEY.format(job_id=job_id))  # type: ignore[misc]
        return _from_hash(fields) if fields else None

    async def require(self, job_id: str) -> JobRecord:
        record = await self.get(job_id)
        if record is None:
            raise JobNotFound(f"no such job: {job_id}")
        return record

    # --- transitions -----------------------------------------------------

    async def mark_running(self, job_id: str) -> JobRecord:
        return await self._transition_to(
            job_id,
            {"status": JobStatus.RUNNING.value, "started_at": self._now().isoformat()},
            allowed_from=[JobStatus.QUEUED],
        )

    async def mark_succeeded(self, job_id: str, result: dict[str, Any]) -> JobRecord:
        return await self._transition_to(
            job_id,
            {
                "status": JobStatus.SUCCEEDED.value,
                "finished_at": self._now().isoformat(),
                "result": result,
            },
            allowed_from=[JobStatus.RUNNING],
        )

    async def mark_failed(self, job_id: str, code: str, message: str) -> JobRecord:
        """Record a failure as a code and a short message.

        The traceback is logged and never stored here, because this record is
        what a caller can read (spec section 7.4).
        """
        return await self._transition_to(
            job_id,
            {
                "status": JobStatus.FAILED.value,
                "finished_at": self._now().isoformat(),
                "error": {"code": code, "message": message},
            },
            allowed_from=[JobStatus.QUEUED, JobStatus.RUNNING],
        )

    async def cancel(self, job_id: str) -> JobRecord:
        """Cancel a job that has not started.

        Compare-and-set inside Redis: this races the worker calling
        ``mark_running``, and exactly one of them must win.
        """
        record = await self._transition_to(
            job_id,
            {"status": JobStatus.CANCELLED.value, "finished_at": self._now().isoformat()},
            allowed_from=[JobStatus.QUEUED],
        )
        if record.status is not JobStatus.CANCELLED:
            raise JobNotCancellable(
                f"job {job_id} is {record.status.value} and can no longer be cancelled",
                details={"status": record.status.value},
            )
        return record

    async def _transition_to(
        self,
        job_id: str,
        changes: dict[str, Any],
        *,
        allowed_from: list[JobStatus],
    ) -> JobRecord:
        flat: list[str] = []
        for field, value in changes.items():
            flat.extend(
                [field, json.dumps(value) if field in _JSON_FIELDS else str(value)]
            )

        status = await self._transition(
            keys=[JOB_KEY.format(job_id=job_id)],
            args=[json.dumps(flat), json.dumps([s.value for s in allowed_from])],
        )
        if status is None:
            raise JobNotFound(f"no such job: {job_id}")
        return await self.require(job_id)

    # --- internals -------------------------------------------------------

    async def _write(self, record: JobRecord) -> None:
        key = JOB_KEY.format(job_id=record.job_id)
        # redis-py types these as sync-or-async; they are async on this client.
        await self._redis.hset(key, mapping=_to_hash(record))  # type: ignore[misc]
        await self._redis.expire(key, self._ttl)


def _decode(value: str | bytes) -> str:
    return value.decode() if isinstance(value, bytes) else value


def _to_hash(record: JobRecord) -> dict[str, str]:
    """Flatten a record into hash fields.

    Only ``request``, ``error`` and ``result`` are JSON; the rest are plain
    strings so a human reading Redis can see what a job is doing.
    """
    document = record.model_dump(mode="json")
    fields: dict[str, str] = {}
    for name, value in document.items():
        if value is None:
            continue
        fields[name] = json.dumps(value) if name in _JSON_FIELDS else str(value)
    return fields


def _from_hash(fields: dict[str | bytes, str | bytes]) -> JobRecord:
    document: dict[str, Any] = {}
    for raw_name, raw_value in fields.items():
        name, value = _decode(raw_name), _decode(raw_value)
        document[name] = json.loads(value) if name in _JSON_FIELDS else value
    return JobRecord.model_validate(document)
