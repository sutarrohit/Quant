"""Stopping an account, when stopping is the only thing that still works.

`Quant-Phase.md` lists a global kill switch among the things live execution
needs. ADR-001 made it more load-bearing than that: `trading-core` no longer
stands between a signal and the venue, so this is the operator's direct line to
a node that is doing something they want stopped.

**More than one path, and any of them is enough.** The question that decides a
kill switch's design is what happens when the thing carrying it is broken —
which is exactly when it is reached for. So:

* a flag in this service's Redis, which is fast and remote;
* a file on the node's own disk, which works when Redis does not;
* and the composite, engaged when **either** says so.

The composite fails *safe* in both directions worth naming: a path that errors
is treated as engaged, because an operator who cannot be heard must not be
assumed to have said nothing. That means a Redis outage stops new orders. It
also means it cannot be silently defeated by breaking one path.

**It is a total stop, exits included.** Every other brake in this system --
a stale risk gate, the daily loss limit, a revoked mandate -- blocks new entries
and lets a position be closed, because an account that cannot shed risk is
dangerous. The kill switch deliberately does not: you reach for one when you do
not trust the strategy, and a strategy you do not trust should not be closing
positions either, since its idea of an exit may be the bug.

The cost is real and is the operator's to carry: the position sits with nothing
managing its stop until a human closes it at the exchange. That is why this is a
separate instrument from the limits, and why it is not the thing to reach for
when you merely want an account to stop opening risk.

It does not flatten either -- turning an operator's "stop" into a realised loss
is a different decision, and it gets a different verb.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

KILL_KEY = "live:kill:{account_id}"
GLOBAL_KILL_KEY = "live:kill:__all__"


class KillSwitch(Protocol):
    async def is_engaged(self, account_id: str) -> bool: ...


class RedisKillSwitch:
    """A flag in this service's own Redis.

    Deliberately not in `trading-core`: an operator must be able to stop a node
    when the service that sets policy is unreachable, which is precisely when
    they are most likely to want to.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def engage(self, account_id: str) -> None:
        await self._redis.set(KILL_KEY.format(account_id=account_id), "1")

    async def release(self, account_id: str) -> None:
        await self._redis.delete(KILL_KEY.format(account_id=account_id))

    async def engage_all(self) -> None:
        await self._redis.set(GLOBAL_KILL_KEY, "1")

    async def release_all(self) -> None:
        await self._redis.delete(GLOBAL_KILL_KEY)

    async def is_engaged(self, account_id: str) -> bool:
        if await self._redis.exists(GLOBAL_KILL_KEY):
            return True
        return bool(await self._redis.exists(KILL_KEY.format(account_id=account_id)))


class FileKillSwitch:
    """A file on the node's own disk.

    The path that survives Redis being down, a network partition, or this
    service's own API being wedged. An operator with a shell can always stop a
    node.
    """

    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)

    def _path(self, account_id: str) -> Path:
        safe = "".join(character for character in account_id if character.isalnum() or character in "-_")
        return self._directory / f"kill-{safe}"

    @property
    def _global_path(self) -> Path:
        return self._directory / "kill-all"

    def engage(self, account_id: str) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        self._path(account_id).touch()

    def release(self, account_id: str) -> None:
        self._path(account_id).unlink(missing_ok=True)

    async def is_engaged(self, account_id: str) -> bool:
        return self._global_path.exists() or self._path(account_id).exists()


class CompositeKillSwitch:
    """Engaged when any path says so, or when any path cannot answer.

    Failing safe on an error is the whole point. A kill switch that quietly
    reports "not engaged" because its backing store is unreachable has removed
    itself at the moment it was needed.
    """

    def __init__(self, *switches: KillSwitch) -> None:
        self._switches = switches

    async def is_engaged(self, account_id: str) -> bool:
        for switch in self._switches:
            try:
                if await switch.is_engaged(account_id):
                    return True
            except Exception:
                logger.exception(
                    "a kill switch could not be read; treating it as engaged",
                    extra={"account_id": account_id, "switch": type(switch).__name__},
                )
                return True
        return False


class NeverEngaged:
    """For backtests and tests. Never used by a live node."""

    async def is_engaged(self, account_id: str) -> bool:
        return False
