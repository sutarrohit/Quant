from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from typing import Any

import pandas as pd
import pytest

from engine.backtest.results import (
    Summary,
    Trade,
    build_equity_curve,
    build_trades,
    summarise,
)

START = datetime(2024, 1, 1, tzinfo=UTC)
END = datetime(2024, 2, 1, tzinfo=UTC)


def positions_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def position(
    *,
    opened: datetime,
    closed: datetime | None,
    qty: str = "0.1",
    open_px: str = "40000",
    close_px: str | None = "42000",
    pnl: str = "200",
    commission: str = "12",
) -> dict[str, Any]:
    return {
        "entry": "BUY",
        "peak_qty": qty,
        "avg_px_open": open_px,
        "avg_px_close": close_px,
        "realized_pnl": f"{pnl} USDT",
        "commissions": [f"{commission} USDT"],
        "ts_opened": opened,
        "ts_closed": closed,
        "duration_ns": ((closed - opened).total_seconds() * 1e9) if closed else 0.0,
    }


def trade(pnl: str, *, opened: datetime = START, hours: int = 1) -> Trade:
    return Trade(
        entry_time=opened,
        exit_time=opened + timedelta(hours=hours),
        side="BUY",
        quantity=D("0.1"),
        entry_price=D(40000),
        exit_price=D(42000),
        pnl=D(pnl),
        return_pct=D("5"),
        commission=D(12),
        fees=D(8),
        slippage=D(4),
        holding_seconds=hours * 3600,
    )


# --- trades --------------------------------------------------------------


def test_only_closed_positions_become_trades() -> None:
    frame = positions_frame(
        [
            position(opened=START, closed=START + timedelta(hours=2)),
            position(opened=START + timedelta(days=1), closed=None, close_px=None),
        ]
    )
    assert len(build_trades(frame, fee_bps=D(10), slippage_bps=D(5))) == 1


def test_costs_are_split_by_their_basis_points() -> None:
    # Both legs are charged, so the notional is entry + exit.
    # (0.1*40000 + 0.1*42000) = 8200. 10bps -> 8.2 fees, 5bps -> 4.1 slippage.
    frame = positions_frame([position(opened=START, closed=START + timedelta(hours=1))])
    result = build_trades(frame, fee_bps=D(10), slippage_bps=D(5))[0]

    assert result.fees == D("8.2")
    assert result.slippage == D("4.1")
    assert result.fees / result.slippage == 2


def test_zero_costs_split_to_zero() -> None:
    frame = positions_frame([position(opened=START, closed=START + timedelta(hours=1))])
    result = build_trades(frame, fee_bps=D(0), slippage_bps=D(0))[0]
    assert result.fees == 0
    assert result.slippage == 0


def test_holding_period_comes_from_the_position() -> None:
    frame = positions_frame([position(opened=START, closed=START + timedelta(hours=3))])
    assert build_trades(frame, fee_bps=D(10), slippage_bps=D(5))[0].holding_seconds == 10800


def test_no_positions_yields_no_trades() -> None:
    assert build_trades(positions_frame([]), fee_bps=D(10), slippage_bps=D(5)) == []


# --- equity curve --------------------------------------------------------


def test_equity_accumulates_pnl() -> None:
    curve = build_equity_curve([trade("100"), trade("-40"), trade("60")], D(1000))
    assert [point.equity for point in curve] == [D(1100), D(1060), D(1120)]


def test_drawdown_is_measured_from_the_peak() -> None:
    curve = build_equity_curve([trade("100"), trade("-200"), trade("50")], D(1000))
    assert curve[0].drawdown == 0
    assert curve[1].drawdown == D("-18.181818")  # 900 against a 1100 peak
    assert curve[2].drawdown == D("-13.636364")


def test_an_empty_curve_for_no_trades() -> None:
    assert build_equity_curve([], D(1000)) == []


# --- summary -------------------------------------------------------------


def summary_of(trades: list[Trade], starting: str = "1000") -> Summary:
    curve = build_equity_curve(trades, D(starting))
    return summarise(trades, curve, starting_equity=D(starting), start=START, end=END)


def test_total_return_and_ending_equity() -> None:
    result = summary_of([trade("100"), trade("-40")])
    assert result.ending_equity == D("1060.00000000")
    assert result.total_return == D("6.000000")


def test_win_rate_and_profit_factor() -> None:
    result = summary_of([trade("100"), trade("-50"), trade("50"), trade("-50")])
    assert result.win_rate == D("50.000000")
    # 150 of profit against 100 of loss.
    assert result.profit_factor == D("1.500000")


def test_profit_factor_is_zero_when_nothing_was_lost() -> None:
    # Not infinity: a summary has to serialise.
    assert summary_of([trade("100")]).profit_factor == 0


def test_average_and_median_trade() -> None:
    result = summary_of([trade("100"), trade("-40"), trade("60")])
    assert result.average_trade == D("40.00000000")
    assert result.median_trade == D("60.00000000")


def test_median_of_an_even_count() -> None:
    assert summary_of([trade("10"), trade("30")]).median_trade == D("20.00000000")


def test_max_drawdown_is_the_worst_point() -> None:
    assert summary_of([trade("100"), trade("-200")]).max_drawdown == D("-18.181818")


def test_costs_are_totalled_separately() -> None:
    # Spec section 7.5 reports fees and slippage as separate lines.
    result = summary_of([trade("100"), trade("-40")])
    assert result.total_fees == D("16.00000000")
    assert result.total_slippage == D("8.00000000")


def test_exposure_is_time_in_position_over_the_window() -> None:
    # Two one-hour trades in a 31-day window.
    result = summary_of([trade("10", hours=1), trade("10", opened=START + timedelta(days=1))])
    expected = D(7200) / D(31 * 24 * 3600) * 100
    assert abs(result.exposure_percent - expected) < D("0.001")


def test_holding_period_is_averaged() -> None:
    result = summary_of([trade("10", hours=1), trade("10", hours=3)])
    assert result.average_holding_seconds == 7200


def test_an_empty_run_summarises_without_dividing_by_zero() -> None:
    result = summary_of([])
    assert result.trade_count == 0
    assert result.total_return == 0
    assert result.win_rate == 0
    assert result.profit_factor == 0
    assert result.sharpe == 0
    assert result.max_drawdown == 0


def test_a_single_trade_has_no_meaningful_sharpe() -> None:
    # One return is not a distribution; reporting a number would invent one.
    assert summary_of([trade("100")]).sharpe == 0


def test_sharpe_is_negative_for_a_losing_run() -> None:
    losing = [trade(f"-{value}", opened=START + timedelta(days=index))
              for index, value in enumerate([50, 40, 60, 30, 70])]
    assert summary_of(losing).sharpe < 0


def test_sortino_ignores_upside_volatility() -> None:
    # Same mean, but one series has all its variance on the upside.
    steady = [trade("20", opened=START + timedelta(days=i)) for i in range(6)]
    assert summary_of(steady).sortino == 0


# --- serialisation -------------------------------------------------------


def test_the_summary_is_all_strings_or_ints() -> None:
    # Money as a JSON float would undo the Decimal discipline.
    document = summary_of([trade("100"), trade("-40")]).to_dict()
    for key, value in document.items():
        assert isinstance(value, str | int), f"{key} is {type(value).__name__}"


def test_summaries_are_deterministic() -> None:
    trades = [trade("100"), trade("-40"), trade("60")]
    assert summary_of(trades).to_dict() == summary_of(trades).to_dict()


@pytest.mark.parametrize(
    "field",
    ["totalReturn", "cagr", "maxDrawdown", "sharpe", "sortino", "winRate", "profitFactor"],
)
def test_ratios_are_quantized(field: str) -> None:
    # Fixed places, so a golden file does not churn on the last digit.
    value = summary_of([trade("100"), trade("-40")]).to_dict()[field]
    assert len(str(value).split(".")[-1]) == 6


# --- open positions ------------------------------------------------------


def test_unrealized_pnl_is_added_to_ending_equity() -> None:
    curve = build_equity_curve([trade("100")], D(1000))
    result = summarise(
        [trade("100")], curve, starting_equity=D(1000), start=START, end=END,
        unrealized_pnl=D(250), open_positions=1,
    )
    assert result.ending_equity == D("1350.00000000")
    assert result.unrealized_pnl == D("250.00000000")
    assert result.open_positions == 1


def test_total_return_reflects_an_open_position() -> None:
    # Excluding it understated a trend follower by 77 percentage points when
    # measured against backtesting.py.
    curve = build_equity_curve([trade("100")], D(1000))
    without = summarise([trade("100")], curve, starting_equity=D(1000), start=START, end=END)
    with_open = summarise(
        [trade("100")], curve, starting_equity=D(1000), start=START, end=END,
        unrealized_pnl=D(250), open_positions=1,
    )
    assert with_open.total_return > without.total_return
    assert without.unrealized_pnl == 0
    assert without.open_positions == 0


def test_a_losing_open_position_reduces_equity() -> None:
    curve = build_equity_curve([trade("100")], D(1000))
    result = summarise(
        [trade("100")], curve, starting_equity=D(1000), start=START, end=END,
        unrealized_pnl=D(-300), open_positions=1,
    )
    assert result.ending_equity == D("800.00000000")
