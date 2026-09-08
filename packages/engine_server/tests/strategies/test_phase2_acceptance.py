"""Phase 2 acceptance (spec section 6).

Three criteria:

* the strategy runs end to end in a ``BacktestNode`` and produces at least one
  round-trip trade;
* the same spec, data and config produce byte-identical fills across three
  runs -- the determinism guarantee of section 12, and the one test in this
  repo that must never be weakened;
* a spec that never triggers produces zero orders and does not raise.
"""

from __future__ import annotations

import copy
from typing import Any

import pandas as pd
import pytest

from tests.strategies.conftest import (
    NON_DETERMINISTIC_COLUMNS,
    requires_catalog,
    run_backtest_reports,
)

pytestmark = requires_catalog


def economic(fills: pd.DataFrame) -> str:
    """The fills report less its one non-deterministic column.

    Only ``init_id`` varies between runs: a UUID4 minted per order-initialized
    event, carrying nothing about the strategy or the result. Everything else
    -- prices, quantities, slippage, commissions, both timestamps, and even
    position and venue order ids -- is compared. See D9.
    """
    return fills.drop(columns=NON_DETERMINISTIC_COLUMNS, errors="ignore").to_csv()


# --- at least one round trip --------------------------------------------


def test_produces_round_trip_trades(rsi_spec: dict[str, Any]) -> None:
    reports = run_backtest_reports(rsi_spec)
    positions = reports["positions"]

    assert len(positions) >= 1
    closed = positions[positions["avg_px_close"].notna()]
    assert len(closed) >= 1, "no position was ever closed"
    assert len(reports["fills"]) >= 2, "a round trip needs an entry and an exit fill"


def test_exits_cluster_at_the_configured_thresholds(rsi_spec: dict[str, Any]) -> None:
    """A spec whose only exits are the two percentage thresholds.

    Every trade must therefore end near +4% or -2%. Returns land slightly
    *past* each threshold because the signal is computed on a closed bar and
    the exit fills on the next one -- bar-close semantics working as
    documented, not slippage.
    """
    rsi_spec["exit"] = {
        "any": [
            {"type": "takeProfitPercent", "value": 4},
            {"type": "stopLossPercent", "value": 2},
        ]
    }
    positions = run_backtest_reports(rsi_spec)["positions"]
    closed = positions[positions["avg_px_close"].notna()]
    returns = closed["realized_return"].astype(float)

    assert len(closed) > 5
    wins = returns[returns > 0]
    losses = returns[returns < 0]

    assert wins.min() >= 0.04, "a winning exit fired before its 4% target"
    assert wins.max() < 0.10, "a take-profit ran far past its target"
    assert losses.max() <= -0.02, "a losing exit fired before its 2% stop"
    assert losses.min() > -0.10, "a stop ran far past its level"


def test_bar_close_semantics_overshoot_the_threshold(rsi_spec: dict[str, Any]) -> None:
    # The overshoot is the observable consequence of evaluating on closed bars
    # and filling on the next. If exits ever landed exactly on the threshold,
    # something would be filling intrabar.
    rsi_spec["exit"] = {"any": [{"type": "stopLossPercent", "value": 2}]}
    positions = run_backtest_reports(rsi_spec, end="2024-02-01")["positions"]
    closed = positions[positions["avg_px_close"].notna()]
    returns = closed["realized_return"].astype(float)
    assert (returns <= -0.02).all()


def test_position_size_matches_the_risk_budget(rsi_spec: dict[str, Any]) -> None:
    # 1% of 10000 equity, 2% stop -> ~5000 notional -> ~0.118 BTC at ~42000.
    positions = run_backtest_reports(rsi_spec)["positions"]
    first = positions.iloc[0]
    notional = float(first["peak_qty"]) * float(first["avg_px_open"])
    assert 3000 < notional < 6000


def test_one_position_at_a_time(rsi_spec: dict[str, Any]) -> None:
    # v1 rejects pyramiding: every position must be flat before the next opens.
    positions = run_backtest_reports(rsi_spec)["positions"]
    assert (positions["side"] == "FLAT").sum() >= len(positions) - 1


# --- determinism ---------------------------------------------------------


def test_three_runs_produce_identical_fills(rsi_spec: dict[str, Any]) -> None:
    """Spec section 12. Do not weaken this test.

    A fresh engine per run, the same spec and the same data. Any divergence
    means something non-deterministic reached an output path: unseeded
    randomness, a wall clock, dict ordering, or float accumulation.
    """
    runs = [
        run_backtest_reports(copy.deepcopy(rsi_spec), end="2024-02-01") for _ in range(3)
    ]
    digests = {economic(run["fills"]) for run in runs}

    assert len(runs[0]["fills"]) > 5, "too few fills to prove anything"
    assert len(digests) == 1, "fills differed between identical runs"


def test_three_runs_produce_identical_positions(rsi_spec: dict[str, Any]) -> None:
    runs = [
        run_backtest_reports(copy.deepcopy(rsi_spec), end="2024-02-01") for _ in range(3)
    ]
    columns = ["side", "peak_qty", "avg_px_open", "avg_px_close", "realized_pnl"]
    digests = {run["positions"][columns].to_csv(index=False) for run in runs}
    assert len(digests) == 1


def test_only_init_id_varies_between_runs(rsi_spec: dict[str, Any]) -> None:
    # Pins the exclusion list. If Nautilus makes another column random, this
    # fails rather than the exclusion quietly growing.
    first = run_backtest_reports(copy.deepcopy(rsi_spec), end="2024-02-01")["fills"]
    second = run_backtest_reports(copy.deepcopy(rsi_spec), end="2024-02-01")["fills"]

    differing = [
        column
        for column in first.columns
        if not first[column].astype(str).equals(second[column].astype(str))
    ]
    assert differing == NON_DETERMINISTIC_COLUMNS


# --- a spec that never triggers ------------------------------------------


def test_a_never_triggering_spec_produces_no_orders(rsi_spec: dict[str, Any]) -> None:
    rsi_spec["entry"] = {"indicator": "rsi", "period": 14, "operator": "greaterThan", "value": 999}
    reports = run_backtest_reports(rsi_spec)
    assert len(reports["orders"]) == 0
    assert len(reports["positions"]) == 0


def test_a_never_triggering_spec_does_not_raise(rsi_spec: dict[str, Any]) -> None:
    rsi_spec["entry"] = {"indicator": "rsi", "period": 14, "operator": "lessThan", "value": -1}
    run_backtest_reports(rsi_spec)  # the assertion is that this returns


def test_an_account_too_small_to_trade_produces_no_orders(rsi_spec: dict[str, Any]) -> None:
    # Sizing rejects below min notional rather than submitting an order the
    # venue would refuse.
    reports = run_backtest_reports(rsi_spec, starting_balances=["1 USDT"], end="2024-02-01")
    assert len(reports["orders"]) == 0


@pytest.mark.parametrize("window", [("2024-01-01", "2024-01-08"), ("2024-06-01", "2024-06-15")])
def test_runs_over_arbitrary_windows(rsi_spec: dict[str, Any], window: tuple[str, str]) -> None:
    start, end = window
    reports = run_backtest_reports(rsi_spec, start=start, end=end)
    assert reports["fills"] is not None
