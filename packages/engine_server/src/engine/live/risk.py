"""Account-level risk limits, enforced where the orders are.

ADR-001 moved the risk kernel here. `trading-core` sets policy but no longer
stands between a signal and the venue, so if it is down and the market moves
**these checks are the only thing between the strategy and the account** -- hence
pure functions with a test each.

**Account-level, not strategy-level.** Five strategies that are all
long-BTC-momentum are one bet at five times the size; per-strategy limits would
let that through.

**The kill switch is checked first and answers alone** -- no arithmetic, no
account state, no venue call. Everything it depends on can be broken when it is
most needed.
"""

from __future__ import annotations

import logging

from engine.types.risk import (
    ALLOWED,
    AccountRisk,
    Breach,
    Decision,
    OrderIntent,
    RiskLimits,
    Verdict,
)

logger = logging.getLogger(__name__)


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
