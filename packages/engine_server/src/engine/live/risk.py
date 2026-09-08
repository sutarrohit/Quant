"""Account-level risk limits, enforced where the orders are.

ADR-001 moved the risk kernel's job into this process. `trading-core` sets
policy; it no longer stands between a signal and the venue. So if it is down
and the market moves, **these checks are the only thing between the strategy and
the account** — which is why they are pure functions with a test each, and why
the kill switch has more than one way to reach a node.

**Account-level, not strategy-level.** `Quant-Phase.md` is specific about this:
a user running five strategies that are all long-BTC-momentum has one bet at
five times the size and does not know it. Limits that bind per strategy would
let that through.

**The kill switch is checked first and answers on its own.** No limit
arithmetic, no account state, no venue call — just "is this account stopped".
Everything a kill switch depends on is something that can be broken when you
most need it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

logger = logging.getLogger(__name__)


class Verdict(StrEnum):
    ALLOW = "ALLOW"
    REJECT = "REJECT"


class Breach(StrEnum):
    KILL_SWITCH = "KILL_SWITCH"
    MANDATE_REVOKED = "MANDATE_REVOKED"
    MAX_ORDER_NOTIONAL = "MAX_ORDER_NOTIONAL"
    MAX_POSITION_NOTIONAL = "MAX_POSITION_NOTIONAL"
    MAX_OPEN_POSITIONS = "MAX_OPEN_POSITIONS"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """What an account may do. ``None`` means unlimited, and is a choice.

    Every value is ``Decimal``: these multiply notionals and compare against
    money, and a float here would be a rounding error in a safety check.
    """

    max_order_notional: Decimal | None = None
    max_position_notional: Decimal | None = None
    max_open_positions: int | None = None
    #: A positive number. Realized loss today beyond this stops new risk.
    daily_loss_limit: Decimal | None = None

    @property
    def is_unlimited(self) -> bool:
        return all(
            value is None
            for value in (
                self.max_order_notional,
                self.max_position_notional,
                self.max_open_positions,
                self.daily_loss_limit,
            )
        )


@dataclass(frozen=True, slots=True)
class AccountRisk:
    """What the account is currently carrying."""

    open_notional: Decimal = Decimal(0)
    open_positions: int = 0
    #: Negative when down. Compared against the loss limit's magnitude.
    realized_pnl_today: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """An order about to be submitted."""

    instrument_id: str
    notional: Decimal
    #: A closing order reduces risk, so most limits do not apply to it.
    reduce_only: bool = False


@dataclass(frozen=True, slots=True)
class Decision:
    verdict: Verdict
    reason: str = ""
    breach: Breach | None = None

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW


ALLOWED = Decision(Verdict.ALLOW)


def evaluate(
    intent: OrderIntent,
    account: AccountRisk,
    limits: RiskLimits,
    *,
    kill_engaged: bool = False,
) -> Decision:
    """Decide whether an order may be submitted. Pure.

    A reduce-only order is exempt from every limit except the kill switch:
    closing a position lowers risk, and refusing it because a limit is already
    breached would trap the account in the position that breached it.
    """
    if kill_engaged:
        # First, and on its own. Nothing below is consulted.
        return Decision(
            Verdict.REJECT, "the kill switch is engaged for this account", Breach.KILL_SWITCH
        )

    if intent.reduce_only:
        return ALLOWED

    if limits.max_order_notional is not None and intent.notional > limits.max_order_notional:
        return Decision(
            Verdict.REJECT,
            f"order notional {intent.notional} exceeds the limit {limits.max_order_notional}",
            Breach.MAX_ORDER_NOTIONAL,
        )

    if limits.max_position_notional is not None:
        after = account.open_notional + intent.notional
        if after > limits.max_position_notional:
            return Decision(
                Verdict.REJECT,
                f"open notional would reach {after}, above the limit "
                f"{limits.max_position_notional}",
                Breach.MAX_POSITION_NOTIONAL,
            )

    if limits.max_open_positions is not None and account.open_positions >= limits.max_open_positions:
        return Decision(
            Verdict.REJECT,
            f"{account.open_positions} positions are open, at the limit "
            f"{limits.max_open_positions}",
            Breach.MAX_OPEN_POSITIONS,
        )

    if limits.daily_loss_limit is not None and account.realized_pnl_today <= -abs(
        limits.daily_loss_limit
    ):
        # The one limit that is about the day rather than the order. It stops
        # new risk; it does not force a close.
        return Decision(
            Verdict.REJECT,
            f"today's realized loss {account.realized_pnl_today} has reached the limit "
            f"{limits.daily_loss_limit}",
            Breach.DAILY_LOSS_LIMIT,
        )

    return ALLOWED
