"""What should be running, and what is (spec section 10.1).

Live is a **state**, not a request: an account should still be trading after a
deploy or a restart. `live/desired_state.py` holds the store over these.

Two records per account, deliberately separate -- **desired** written by the
API, **observed** written by the supervisor. That is what makes the loop a
reconciliation rather than a command.

**Credentials are never here.** The record carries a ``credential_ref``; the
node resolves it at startup and holds the key in memory only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from engine.types.risk import RiskLimits


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

        Crashing is a fact about the process, so restarting is right. Disagreeing
        with the venue is a fact about the money, and retrying every five seconds
        is being wrong faster. Cleared by an operator re-stating the
        desired state, which bumps the revision.
        """
        return self is ObservedStatus.HALTED


class TradingMode(StrEnum):
    """Which of Nautilus's environments an account runs in.

    Named for Nautilus's vocabulary rather than "paper", so the mode, the package
    and the value Nautilus is given all say the same word -- three names for one
    thing is how a node declares itself live while running a simulator (D17).

    ``SIMULATION`` needs no credentials and risks no money.
    """

    SIMULATION = "SIMULATION"
    LIVE = "LIVE"


class WireModel(BaseModel):
    """A model that is both stored in Redis and accepted from an HTTP body.

    The alias generator is why these accept camelCase: without it they were the
    only snake_case objects on an otherwise camelCase surface, so `makerBps`
    inside `fees` was a 422 while `strategyVersionId` beside it was fine.

    `populate_by_name` keeps snake_case working, because records already in Redis
    were written with field names and must still read back.
    """

    model_config = ConfigDict(
        frozen=True, extra="forbid", alias_generator=to_camel, populate_by_name=True
    )


class RiskLimitsModel(WireModel):
    """Account-level limits, as JSON.

    Account-level, not per strategy: five long-BTC-momentum strategies are one
    bet at five times the size. Decimal from strings, since these compare money.
    """

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


class VenueFees(WireModel):
    """What the venue charges this account, in basis points.

    **Required, never defaulted to zero.** A backtest with no fees is a marketing
    number; a simulation with no fees is one someone may act on.

    Declared rather than discovered: Binance's public endpoint reports
    `maker_fee: 0` (verified, D20), and the real rates need a key ADR-001
    forbids. Decimal from strings, since these multiply notionals.
    """

    maker_bps: Decimal = Field(ge=0, le=10_000)
    taker_bps: Decimal = Field(ge=0, le=10_000)
    slippage_bps: Decimal = Field(ge=0, le=10_000)

    @property
    def cost_bps(self) -> Decimal:
        """What sizing must leave room for on one entry.

        Taker plus slippage, matching `backtest/builder.py` exactly -- sizing the
        two differently would make them incomparable.
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

        Not "might be" -- a node holding a position with nobody managing its stop
        is the worst state the system can be in, so the supervisor acts.
        """
        if not self.status.is_live:
            return False
        if self.heartbeat_at is None:
            return True
        return (now - self.heartbeat_at).total_seconds() > timeout_seconds
