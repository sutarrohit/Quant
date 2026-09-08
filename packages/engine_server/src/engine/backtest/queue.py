"""Handing a job to the worker.

The API's only job after validating is to enqueue. Running a backtest in the
request handler pins a CPU for minutes and blocks the event loop, which takes
the service down under two concurrent users (spec section 7.1).

A protocol rather than a direct arq call, for one reason: the API's contract
is that a bad spec never reaches the queue, and that has to be *observable*.
A test double records what was enqueued, so `assert queue.enqueued == []` says
exactly what section 7.6 asks. Calling arq directly would mean faking an
``ArqRedis`` -- a Redis subclass whose ``enqueue_job`` returns a ``Job`` -- to
assert something about our own behaviour.

It is not here to make the transport swappable. arq owns the queue format, and
nothing plans to replace it.
"""

from __future__ import annotations

from typing import Protocol

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

#: The task name the worker registers in Step 15.
RUN_BACKTEST_TASK = "run_backtest"


class JobQueue(Protocol):
    async def enqueue(self, job_id: str) -> None:
        """Hand a job to a worker. Must not block."""
        ...


class ArqJobQueue:
    """arq-backed queue.

    The job id is passed as arq's own ``_job_id`` as well, so a duplicate
    enqueue of the same job is dropped by arq rather than running twice --
    a second line of defence behind the idempotent claim.
    """

    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, redis_url: str) -> ArqJobQueue:
        return cls(await create_pool(RedisSettings.from_dsn(redis_url)))

    async def enqueue(self, job_id: str) -> None:
        await self._pool.enqueue_job(RUN_BACKTEST_TASK, job_id, _job_id=job_id)

    async def close(self) -> None:
        await self._pool.aclose()
