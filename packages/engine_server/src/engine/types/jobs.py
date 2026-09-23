"""A backtest job as it is stored (spec sections 7.2, 9).

Job bookkeeping with a TTL -- never the financial record. `store/jobs.py` holds
the Redis operations over these.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    #: Fetching market data the catalog does not hold yet. A state of its own
    #: rather than part of RUNNING: a cold two-year window is minutes of paging
    #: against the venue, and a caller watching a progress bar deserves to know
    #: the difference between "downloading history" and "computing".
    FETCHING_DATA = "FETCHING_DATA"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def terminal(self) -> bool:
        return self in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)


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
