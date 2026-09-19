"""What should be running, and what is (spec section 10.1).

A backtest is a request: submit it, it runs, it finishes. Live is a **state**:
an account should be trading a strategy, and it should still be trading it
after a deploy, a crash, or the API restarting. Those are different kinds of
thing, and an HTTP request models only the first.

So the API does not start a node. It records a desire, and a supervisor
converges on it. Restarting the API changes nothing about what is trading,
which is the property that actually matters.

Two records per account, deliberately separate:

* **desired** -- written by the API. What should be true.
* **observed** -- written by the supervisor. What is true.

Keeping them apart is what makes the loop a reconciliation rather than a
command. A command that is lost leaves the system wrong; a desire that is not
yet met is simply not met yet, and the next pass tries again.

**Credentials are never here.** The record carries a ``credential_ref``; the
node resolves it at startup and holds the key in memory only. A key in this
record would be a key in Redis, in a backup of Redis, and in whatever reads it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

from engine.errors import AccountNotFound
from engine.live.risk import RiskLimits
from engine.settings import Settings

DESIRED_KEY = "live:desired:{account_id}"
OBSERVED_KEY = "live:observed:{account_id}"
ACCOUNTS_KEY = "live:accounts"
LEASE_KEY = "live:lease:{account_id}"


class DesiredStatus(StrEnum):
    """What the operator wants."""

    RUNNING = "RUNNING"
    STOPPED = "STOPPED"


class ObservedStatus(StrEnum):
    """What the supervisor sees."""

    STARTING = "STARTING"
    RECONCILING = "RECONCILING"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    #: Disagreed with the venue on startup. Not retried: see `needs_operator`.
    HALTED = "HALTED"

    @property
    def is_live(self) -> bool:
        return self in (ObservedStatus.STARTING, ObservedStatus.RECONCILING, ObservedStatus.RUNNING)

    @property
    def needs_operator(self) -> bool:
        """A state the supervisor must not clear by itself.

        Crashing is a fact about the process, and restarting is the right
        answer. Disagreeing with the venue is a fact about the money, and a
        node that hammers the exchange every five seconds while wrong is not
        recovering -- it is being wrong faster. Spec section 10.3 calls for a
        halted state, and this is it: cleared by an operator re-stating the
        desired state, which bumps the revision.
        """
        return self is ObservedStatus.HALTED


class TradingMode(StrEnum):
    """Which of Nautilus's environments an account runs in.

    Named for Nautilus's own vocabulary rather than the industry's "paper", so
    that the mode, the package (`engine.simulation`) and the value Nautilus is
    given (`Environment.SANDBOX`) all say the same word. Three names for one
    thing is how a node ends up declaring itself live while running a simulated
    exchange (D17).

    ``SIMULATION`` needs no credentials and risks no money. It is also the
    integration test for the whole system, and where a data feed reveals a lag
    nobody knew about.
    """

    SIMULATION = "SIMULATION"
    LIVE = "LIVE"


class RiskLimitsModel(BaseModel):
    """Account-level limits, as JSON.

    Account-level rather than per strategy: five strategies that are all
    long-BTC-momentum are one bet at five times the size, and limits that bind
    per strategy would let that through.

    Decimal from strings, because these compare against money.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_order_notional: Decimal | None = Field(default=None, gt=0)
    max_position_notional: Decimal | None = Field(default=None, gt=0)
    max_open_positions: int | None = Field(default=None, ge=1)
    daily_loss_limit: Decimal | None = Field(default=None, gt=0)

    def to_limits(self) -> RiskLimits:
        return RiskLimits(
            max_order_notional=self.max_order_notional,
            max_position_notional=self.max_position_notional,
            max_open_positions=self.max_open_positions,
            daily_loss_limit=self.daily_loss_limit,
        )


class VenueFees(BaseModel):
    """What the venue charges this account, in basis points.

    **Required, and never defaulted to zero** -- the same rule a backtest lives
    under (rule 5), and for a stronger reason here. A backtest with no fees is
    a marketing number; a simulation with no fees is a marketing number someone
    may act on.

    It has to be declared rather than discovered. A Binance instrument fetched
    from the public endpoint reports `maker_fee: 0, taker_fee: 0` -- verified,
    not assumed. Real rates are account-specific and live behind an
    authenticated endpoint, which needs a key, which ADR-001 forbids. So the
    venue cannot tell us, and the operator must (D20).

    Decimal from strings, because these multiply notionals.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    maker_bps: Decimal = Field(ge=0, le=10_000)
    taker_bps: Decimal = Field(ge=0, le=10_000)
    slippage_bps: Decimal = Field(ge=0, le=10_000)

    @property
    def cost_bps(self) -> Decimal:
        """What sizing must leave room for on one entry.

        Taker plus slippage, matching `backtest/builder.py` exactly -- a
        strategy sized one way in simulation and another in backtest would make
        the two incomparable, which is the whole point of running the same
        class in both.
        """
        return self.taker_bps + self.slippage_bps


class DesiredState(BaseModel):
    """What an account should be doing."""

    model_config = ConfigDict(frozen=True)

    account_id: str = Field(min_length=1, max_length=128)
    venue: str
    instrument_id: str
    bar_type: str
    spec: dict[str, Any]
    strategy_version_id: str
    spec_hash: str
    mode: TradingMode
    #: A pointer to a secret held elsewhere, never the secret. Absent for simulation.
    credential_ref: str | None = None
    #: What this account may do. ADR-001 made these the only thing between a
    #: strategy and the account when trading-core is unreachable.
    risk: RiskLimitsModel = Field(default_factory=lambda: RiskLimitsModel())
    #: What the venue charges. No default: see `VenueFees`.
    fees: VenueFees
    status: DesiredStatus = DesiredStatus.RUNNING
    #: Bumped on every write. The supervisor restarts a node whose running
    #: revision no longer matches, which is how a spec change takes effect.
    revision: int = 1
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_response(self) -> dict[str, Any]:
        document = self.model_dump(mode="json")
        # Even a reference is not something to hand back by default.
        document.pop("credential_ref", None)
        return document


class ObservedState(BaseModel):
    """What the supervisor last saw."""

    model_config = ConfigDict(frozen=True)

    account_id: str
    status: ObservedStatus
    #: Which desired revision this node is actually running.
    revision: int = 0
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    error: dict[str, Any] | None = None

    def is_stale(self, *, now: datetime, timeout_seconds: int) -> bool:
        """A node that has stopped heartbeating is presumed dead.

        Not "might be dead" -- the supervisor must act on it, because a node
        holding a position with nobody managing its stop is the worst state the
        system can be in.
        """
        if not self.status.is_live:
            return False
        if self.heartbeat_at is None:
            return True
        return (now - self.heartbeat_at).total_seconds() > timeout_seconds


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
