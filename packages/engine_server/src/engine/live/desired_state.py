"""What should be running, and what is (spec section 10.1).

A backtest is a request that finishes. Live is a **state** that should still be
true after a deploy, a crash, or the API restarting -- so the API records a
desire and a supervisor converges on it, rather than starting a node itself.

Two records per account, deliberately separate:

* **desired** -- written by the API. What should be true.
* **observed** -- written by the supervisor. What is true.

Keeping them apart makes the loop a reconciliation rather than a command: a lost
command leaves the system wrong, an unmet desire is simply retried.

**Credentials are never here.** The record carries a ``credential_ref``; the node
resolves it at startup and holds the key in memory only.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Self

from redis.asyncio import Redis

from engine.errors import AccountNotFound
from engine.settings import Settings
from engine.types.state import DesiredState, DesiredStatus, ObservedState

DESIRED_KEY = "live:desired:{account_id}"
OBSERVED_KEY = "live:observed:{account_id}"
ACCOUNTS_KEY = "live:accounts"
LEASE_KEY = "live:lease:{account_id}"


class LiveStateStore:
    """Reads and writes the two records, plus the single-node lease."""

    def __init__(
        self,
        redis: Redis,
        *,
        lease_seconds: int = 30,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._redis = redis
        self._lease_seconds = lease_seconds
        self._now = now

    @classmethod
    def from_settings(cls, settings: Settings, redis: Redis) -> Self:
        return cls(redis, lease_seconds=settings.live_lease_seconds)

    # --- desired ---------------------------------------------------------

    async def put(self, state: DesiredState) -> DesiredState:
        """Record what an account should be doing.

        Idempotent in the way that matters: writing the same intent twice
        leaves one record and one account. A POST that started a node would
        instead have started two, both trading the same account.
        """
        existing = await self.get(state.account_id)
        revision = (existing.revision + 1) if existing else 1
        stored = state.model_copy(update={"revision": revision, "updated_at": self._now()})

        await self._redis.set(
            DESIRED_KEY.format(account_id=state.account_id), stored.model_dump_json()
        )
        await self._redis.sadd(ACCOUNTS_KEY, state.account_id)  # type: ignore[misc]
        return stored

    async def get(self, account_id: str) -> DesiredState | None:
        raw = await self._redis.get(DESIRED_KEY.format(account_id=account_id))
        return None if raw is None else DesiredState.model_validate_json(_text(raw))

    async def require(self, account_id: str) -> DesiredState:
        state = await self.get(account_id)
        if state is None:
            raise AccountNotFound(f"no live state for account {account_id}")
        return state

    async def stop(self, account_id: str) -> DesiredState:
        """Ask for an account to stop trading.

        The record is kept rather than deleted: the supervisor still has to act
        on it, and a deleted row is indistinguishable from one that was never
        written.
        """
        current = await self.require(account_id)
        return await self.put(current.model_copy(update={"status": DesiredStatus.STOPPED}))

    async def forget(self, account_id: str) -> None:
        """Remove an account entirely. Only safe once it is observed stopped."""
        await self._redis.delete(DESIRED_KEY.format(account_id=account_id))
        await self._redis.delete(OBSERVED_KEY.format(account_id=account_id))
        await self._redis.srem(ACCOUNTS_KEY, account_id)  # type: ignore[misc]

    async def accounts(self) -> list[str]:
        members = await self._redis.smembers(ACCOUNTS_KEY)  # type: ignore[misc]
        return sorted(_text(member) for member in members)

    # --- observed --------------------------------------------------------

    async def observe(self, state: ObservedState) -> None:
        await self._redis.set(
            OBSERVED_KEY.format(account_id=state.account_id), state.model_dump_json()
        )

    async def observed(self, account_id: str) -> ObservedState | None:
        raw = await self._redis.get(OBSERVED_KEY.format(account_id=account_id))
        return None if raw is None else ObservedState.model_validate_json(_text(raw))

    async def heartbeat(self, account_id: str) -> None:
        current = await self.observed(account_id)
        if current is None:
            return
        await self.observe(current.model_copy(update={"heartbeat_at": self._now()}))

    # --- lease -----------------------------------------------------------

    async def acquire(self, account_id: str, holder: str) -> bool:
        """Claim the right to run one account.

        One node per account, enforced rather than assumed: an account is the
        unit of risk, credentials and reconciliation, and two nodes trading it
        would each believe they held the whole position.
        """
        won = await self._redis.set(
            LEASE_KEY.format(account_id=account_id), holder, nx=True, ex=self._lease_seconds
        )
        if won:
            return True
        # Re-entrant for the holder, so a supervisor keeps its own lease.
        current = await self._redis.get(LEASE_KEY.format(account_id=account_id))
        if current is not None and _text(current) == holder:
            await self._redis.expire(LEASE_KEY.format(account_id=account_id), self._lease_seconds)
            return True
        return False

    async def release(self, account_id: str, holder: str) -> None:
        current = await self._redis.get(LEASE_KEY.format(account_id=account_id))
        if current is not None and _text(current) == holder:
            await self._redis.delete(LEASE_KEY.format(account_id=account_id))

    async def lease_holder(self, account_id: str) -> str | None:
        raw = await self._redis.get(LEASE_KEY.format(account_id=account_id))
        return None if raw is None else _text(raw)


def _text(value: str | bytes) -> str:
    return value.decode() if isinstance(value, bytes) else value
