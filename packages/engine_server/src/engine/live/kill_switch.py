"""Stopping an account, when stopping is the only thing that still works.

Since ADR-001, `trading-core` no longer stands between a signal and the venue,
so this is the operator's direct line to a node.

**More than one path, any of them enough** -- because a kill switch is reached
for exactly when the thing carrying it is broken:

* a flag in this service's Redis, fast and remote;
* a file on the node's own disk, which works when Redis does not;
* the composite, engaged when **either** says so.

It fails *safe*: a path that errors counts as engaged, since an operator who
cannot be heard must not be assumed to have said nothing. A Redis outage stops
new orders, and breaking one path cannot silently defeat it.

**A total stop, exits included.** Every other brake here blocks new entries and
lets a position close. This one does not: you reach for it when you do not trust
the strategy, and its idea of an exit may be the bug. The cost is the operator's
-- the position sits unmanaged until a human closes it at the exchange.

It does not flatten either; that is a different decision with a different verb.
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
