"""Account-level risk limits.

ADR-001 moved the risk kernel's job into this process. If trading-core is down
and the market moves, these checks are the only thing between the strategy and
the account — so each one gets a test, and the boundaries get two.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from engine.live.risk import evaluate
from engine.types.risk import AccountRisk, Breach, OrderIntent, RiskLimits


def intent(notional: str = "1000", reduce_only: bool = False) -> OrderIntent:
    return OrderIntent(
        instrument_id="BTCUSDT.BINANCE", notional=D(notional), reduce_only=reduce_only
    )


def account(**overrides: object) -> AccountRisk:
    return AccountRisk(**overrides)  # type: ignore[arg-type]


# --- the kill switch answers first ---------------------------------------


def test_the_kill_switch_rejects_everything() -> None:
    """First, and on its own.

    No limit arithmetic, no account state, no venue call. Everything a kill
    switch depends on is something that can be broken when it is needed.
    """
    decision = evaluate(intent(), account(), RiskLimits(), kill_engaged=True)

    assert decision.allowed is False
    assert decision.breach is Breach.KILL_SWITCH


def test_the_kill_switch_also_stops_a_closing_order() -> None:
    # A stop means stop. Flattening is a different verb.
    decision = evaluate(intent(reduce_only=True), account(), RiskLimits(), kill_engaged=True)
    assert decision.breach is Breach.KILL_SWITCH


def test_the_kill_switch_wins_over_an_otherwise_fine_order() -> None:
    decision = evaluate(
        intent("1"), account(), RiskLimits(max_order_notional=D(1_000_000)), kill_engaged=True
    )
    assert decision.breach is Breach.KILL_SWITCH


# --- unlimited is a choice -----------------------------------------------


def test_no_limits_allows_anything() -> None:
    assert evaluate(intent("999999999"), account(), RiskLimits()).allowed is True


def test_unlimited_is_reported_as_such() -> None:
    assert RiskLimits().is_unlimited is True
    assert RiskLimits(max_order_notional=D(1)).is_unlimited is False


# --- order size ----------------------------------------------------------


def test_an_order_above_the_limit_is_rejected() -> None:
    decision = evaluate(intent("5001"), account(), RiskLimits(max_order_notional=D(5000)))
    assert decision.breach is Breach.MAX_ORDER_NOTIONAL


def test_an_order_exactly_at_the_limit_is_allowed() -> None:
    assert evaluate(intent("5000"), account(), RiskLimits(max_order_notional=D(5000))).allowed


# --- total exposure ------------------------------------------------------


def test_an_order_that_would_breach_total_exposure_is_rejected() -> None:
    # The limit is on what the account would hold afterwards, not on the order.
    decision = evaluate(
        intent("3000"),
        account(open_notional=D(8000)),
        RiskLimits(max_position_notional=D(10_000)),
    )
    assert decision.breach is Breach.MAX_POSITION_NOTIONAL
    assert "11000" in decision.reason


def test_an_order_that_fits_within_total_exposure_is_allowed() -> None:
    assert evaluate(
        intent("2000"),
        account(open_notional=D(8000)),
        RiskLimits(max_position_notional=D(10_000)),
    ).allowed


# --- position count ------------------------------------------------------


def test_opening_beyond_the_position_count_is_rejected() -> None:
    decision = evaluate(
        intent(), account(open_positions=3), RiskLimits(max_open_positions=3)
    )
    assert decision.breach is Breach.MAX_OPEN_POSITIONS


def test_opening_below_the_position_count_is_allowed() -> None:
    assert evaluate(intent(), account(open_positions=2), RiskLimits(max_open_positions=3)).allowed


# --- the daily loss limit ------------------------------------------------


def test_reaching_the_daily_loss_limit_stops_new_risk() -> None:
    decision = evaluate(
        intent(), account(realized_pnl_today=D(-500)), RiskLimits(daily_loss_limit=D(500))
    )
    assert decision.breach is Breach.DAILY_LOSS_LIMIT


def test_being_below_the_daily_loss_limit_is_allowed() -> None:
    assert evaluate(
        intent(), account(realized_pnl_today=D(-499)), RiskLimits(daily_loss_limit=D(500))
    ).allowed


def test_a_profitable_day_is_never_a_breach() -> None:
    assert evaluate(
        intent(), account(realized_pnl_today=D(5000)), RiskLimits(daily_loss_limit=D(500))
    ).allowed


def test_the_limit_is_read_as_a_magnitude() -> None:
    # Whether the operator writes 500 or -500, they mean the same thing.
    for limit in (D(500), D(-500)):
        assert (
            evaluate(
                intent(), account(realized_pnl_today=D(-600)), RiskLimits(daily_loss_limit=limit)
            ).breach
            is Breach.DAILY_LOSS_LIMIT
        )


# --- closing is always allowed -------------------------------------------


@pytest.mark.parametrize(
    "limits",
    [
        RiskLimits(max_order_notional=D(1)),
        RiskLimits(max_position_notional=D(1)),
        RiskLimits(max_open_positions=1),
        RiskLimits(daily_loss_limit=D(1)),
    ],
)
def test_a_closing_order_is_exempt_from_every_limit(limits: RiskLimits) -> None:
    """Refusing to close would trap the account in the position that breached
    the limit, which is the opposite of what a limit is for."""
    decision = evaluate(
        intent("999999", reduce_only=True),
        account(open_notional=D(999999), open_positions=99, realized_pnl_today=D(-99999)),
        limits,
    )
    assert decision.allowed is True


# --- the first breach is the one reported --------------------------------


def test_a_breach_names_the_limit_and_the_numbers() -> None:
    decision = evaluate(intent("9000"), account(), RiskLimits(max_order_notional=D(5000)))
    assert "9000" in decision.reason
    assert "5000" in decision.reason


# --- the kill switch is a total stop -------------------------------------


def test_the_kill_switch_blocks_exits_as_well() -> None:
    """The one brake in this system that also stops a close.

    Every other -- a stale gate, the daily loss limit, a revoked mandate --
    blocks new entries and lets a position be shed. The kill switch does not,
    deliberately: you reach for one when you do not trust the strategy, and a
    strategy you do not trust should not be closing positions either, since its
    idea of an exit may be the bug.

    Pinned by a test because the docs said the opposite of the code for a week
    and nothing caught it. The position becomes the operator's to close at the
    exchange, which is a real cost and the reason this is a separate instrument
    from the limits.
    """
    closing = OrderIntent(instrument_id="BTCUSDT.BINANCE", notional=D(100), reduce_only=True)

    decision = evaluate(closing, AccountRisk(), RiskLimits(), kill_engaged=True)

    assert not decision.allowed
    assert decision.breach is Breach.KILL_SWITCH


def test_every_other_brake_still_lets_a_position_close() -> None:
    # The contrast that makes the rule above legible rather than arbitrary.
    closing = OrderIntent(instrument_id="BTCUSDT.BINANCE", notional=D(100), reduce_only=True)
    breached = RiskLimits(
        max_order_notional=D(1),
        max_position_notional=D(1),
        max_open_positions=1,
        daily_loss_limit=D(1),
    )
    carrying = AccountRisk(
        open_notional=D(10_000), open_positions=5, realized_pnl_today=D(-9_999)
    )

    assert evaluate(closing, carrying, breached).allowed
