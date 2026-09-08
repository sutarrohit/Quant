"""Phase 4 acceptance: this service against backtesting.py (spec section 8).

An independent, widely used engine, run on the same data with the same rules.
`backtesting.py` is a dev dependency only -- nothing in the service imports it.

The comparison is against the *running* engine rather than its published
figures, because those do not reproduce: their documented example claims 718.12%
and version 0.6.6 gives 462.64%, while the data-derived metrics match exactly.
See docs/reproduction-benchmark-search.md.

Two of the engines' structural differences are configured away rather than
tolerated, so what remains is genuinely comparable:

* ``trade_on_close=True`` makes the reference fill where this service fills
  (D12), instead of at the next bar's open;
* the strategy is long-only on both sides, since this DSL has no short side.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from engine.backtest.request import BacktestRequest
from engine.backtest.runner import execute
from engine.settings import Settings

CATALOG = Path("catalog")
BAR_TYPE = "GOOG.NASDAQ-1-DAY-LAST-EXTERNAL"
FAST, SLOW = 10, 20
CASH = 10_000
COMMISSION = 0.002

pytestmark = [
    pytest.mark.skipif(
        not (CATALOG / "data" / "bar" / BAR_TYPE).exists(),
        reason="needs the GOOG reference series; see docs/reproduction-sma-cross-goog.md",
    ),
    pytest.mark.slow,
]


def reference() -> dict[str, Any]:
    """backtesting.py, configured to match this service's fill timing."""
    from backtesting import Backtest, Strategy
    from backtesting.lib import crossover
    from backtesting.test import GOOG, SMA

    class SmaCrossLongOnly(Strategy):
        n1, n2 = FAST, SLOW

        def init(self) -> None:
            self.sma1 = self.I(SMA, self.data.Close, self.n1)
            self.sma2 = self.I(SMA, self.data.Close, self.n2)

        def next(self) -> None:
            if crossover(self.sma1, self.sma2):
                self.buy()
            elif crossover(self.sma2, self.sma1) and self.position:
                self.position.close()

    stats = Backtest(
        GOOG,
        SmaCrossLongOnly,
        cash=CASH,
        commission=COMMISSION,
        trade_on_close=True,
        finalize_trades=False,
    ).run()
    trades = stats["_trades"]
    closed = trades[trades["ExitPrice"].notna()]
    return {
        "stats": stats,
        "closed": closed,
        "closed_pnl": Decimal(str(round(float(closed["PnL"].sum()), 8))),
        "final_equity": Decimal(str(round(float(stats["Equity Final [$]"]), 8))),
        "win_rate": float(stats["Win Rate [%]"]),
        "trades": len(closed),
    }


def ours() -> Any:
    from engine.data.sources.csv_file import _register_ticker

    _register_ticker("GOOG")
    spec = {
        "strategyId": "sma-cross-goog",
        "version": 1,
        "market": {
            "exchange": "binance",
            "marketType": "spot",
            "symbols": ["GOOG/USD"],
            "timeframe": "1d",
        },
        "entry": {
            "indicator": "sma",
            "period": FAST,
            "operator": "crossesAbove",
            "reference": {"indicator": "sma", "period": SLOW},
        },
        "exit": {
            "any": [
                {
                    "indicator": "sma",
                    "period": FAST,
                    "operator": "crossesBelow",
                    "reference": {"indicator": "sma", "period": SLOW},
                },
                # riskPercent sizing requires a stop; 99% never triggers, which
                # makes the crossover the only exit -- as in the reference.
                {"type": "stopLossPercent", "value": 99},
            ]
        },
        "sizing": {"type": "riskPercent", "riskPercent": 99},
    }
    request = BacktestRequest.model_validate(
        {
            "requestId": "req_goog",
            "strategyVersionId": "sv_goog",
            "spec": spec,
            "venue": "NASDAQ",
            "instrumentId": "GOOG.NASDAQ",
            "barType": BAR_TYPE,
            "start": "2004-08-19T00:00:00Z",
            "end": "2013-03-02T00:00:00Z",
            "startingBalances": [f"{CASH} USD"],
            "fees": {"makerBps": "20", "takerBps": "20"},
            "slippageBps": "0",
        }
    )
    return execute(
        request,
        Settings(_env_file=None, catalog_path="./catalog", internal_api_key="x", log_level="ERROR"),
    )


@pytest.fixture(scope="module")
def comparison() -> tuple[dict[str, Any], Any]:
    return reference(), ours()


def test_the_same_trades_are_taken(comparison: tuple[dict[str, Any], Any]) -> None:
    theirs, mine = comparison
    assert theirs["trades"] > 40, "too few trades to prove anything"
    assert len(mine.trades) == theirs["trades"]


def test_every_trade_agrees(comparison: tuple[dict[str, Any], Any]) -> None:
    """Quantity, entry and exit, trade by trade, across all of them."""
    theirs, mine = comparison

    for index in range(len(mine.trades)):
        expected = theirs["closed"].iloc[index]
        produced = mine.trades[index]
        assert int(Decimal(produced["quantity"])) == int(expected["Size"]), f"trade {index} size"
        assert abs(Decimal(produced["entryPrice"]) - Decimal(str(expected["EntryPrice"]))) < Decimal(
            "0.005"
        ), f"trade {index} entry"
        assert abs(Decimal(produced["exitPrice"]) - Decimal(str(expected["ExitPrice"]))) < Decimal(
            "0.005"
        ), f"trade {index} exit"


def test_closed_trade_profit_agrees(comparison: tuple[dict[str, Any], Any]) -> None:
    """The measure both engines compute identically.

    A cent of difference on tens of thousands of dollars is rounding in the
    commission arithmetic, not a modelling disagreement.
    """
    theirs, mine = comparison
    ours_pnl = sum(Decimal(trade["pnl"]) for trade in mine.trades)
    assert abs(ours_pnl - theirs["closed_pnl"]) < Decimal("0.10")


def test_final_equity_agrees(comparison: tuple[dict[str, Any], Any]) -> None:
    """Including the position still open on the last bar.

    Marking it to market is what makes this comparable at all; without it the
    reported return was 77 percentage points low, because a trend follower is
    usually still holding when the data ends.
    """
    theirs, mine = comparison
    ending = Decimal(mine.summary["endingEquity"])
    assert abs(ending - theirs["final_equity"]) < Decimal("0.10")


def test_win_rate_agrees(comparison: tuple[dict[str, Any], Any]) -> None:
    theirs, mine = comparison
    assert abs(float(mine.summary["winRate"]) - theirs["win_rate"]) < 0.01


def test_the_open_position_is_reported(comparison: tuple[dict[str, Any], Any]) -> None:
    _, mine = comparison
    assert mine.summary["openPositions"] == 1
    assert Decimal(mine.summary["unrealizedPnl"]) > 0
