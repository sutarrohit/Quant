#!/usr/bin/env python
"""Run one strategy through this service and through backtesting.py, and compare.

    uv run python scripts/compare_engines.py
    uv run python scripts/compare_engines.py --trades      # trade by trade
    uv run python scripts/compare_engines.py --fill-study  # what fill timing costs

This is the Phase 4 reproduction (spec §8) as something you can run. The
reference is `backtesting.py` — an independent, widely used engine, installed as
a dev dependency and imported nowhere in the service itself.

Two of the engines' structural differences are configured away rather than
tolerated, so what remains is genuinely comparable:

  * `trade_on_close=True` makes the reference fill where this service fills
    (docs/nautilus-api-notes.md D12), instead of at the next bar's open;
  * the strategy is long-only on both sides, since this DSL has no short side.

The GOOG series is ingested on first run, through the normal ingest path.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "GOOG.csv"

BAR_TYPE = "GOOG.NASDAQ-1-DAY-LAST-EXTERNAL"
FAST, SLOW = 10, 20
CASH = 10_000
COMMISSION_BPS = "20"
START, END = "2004-08-19", "2013-03-02"

GREEN, RED, DIM, BOLD, OFF = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


# --- the strategy, expressed twice ---------------------------------------


def dsl_spec() -> dict[str, Any]:
    """The strategy as this service's DSL."""
    crossover = {
        "indicator": "sma",
        "period": FAST,
        "operator": "crossesAbove",
        "reference": {"indicator": "sma", "period": SLOW},
    }
    return {
        "strategyId": "sma-cross-goog",
        "version": 1,
        "market": {
            "exchange": "binance",
            "marketType": "spot",
            "symbols": ["GOOG/USD"],
            "timeframe": "1d",
        },
        "entry": crossover,
        "exit": {
            "any": [
                {**crossover, "operator": "crossesBelow"},
                # riskPercent sizing requires a stop. 99% never triggers, which
                # leaves the crossover as the only exit -- as in the reference.
                {"type": "stopLossPercent", "value": 99},
            ]
        },
        "sizing": {"type": "riskPercent", "riskPercent": 99},
    }


def reference_strategy() -> Any:
    """The same strategy as backtesting.py sees it."""
    from backtesting import Strategy
    from backtesting.lib import crossover
    from backtesting.test import SMA

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

    return SmaCrossLongOnly


# --- running each side ---------------------------------------------------


def ensure_data(catalog_path: str) -> None:
    """Ingest the reference series if the catalog does not hold it yet."""
    from engine.data.catalog import Catalog

    if BAR_TYPE in Catalog(catalog_path).bar_types():
        return

    print(f"{DIM}ingesting {FIXTURE.name} (first run only)...{OFF}")
    from engine.data.ingest import ingest
    from engine.data.raw import RawStore
    from engine.data.sources.csv_file import CsvSource
    from engine.data.timeframes import Timeframe

    source = CsvSource(
        FIXTURE,
        symbol="GOOG",
        venue="NASDAQ",
        base_currency="GOOG",
        quote_currency="USD",
        price_increment=Decimal("0.01"),
        size_increment=Decimal("1"),  # whole shares
        min_notional=Decimal("1"),
        register_base_currency=True,
    )
    result = ingest(
        source=source,
        catalog=Catalog(catalog_path),
        raw_store=RawStore("./raw"),
        symbol="GOOG",
        venue="NASDAQ",
        timeframe=Timeframe.D1,
        start=datetime(2004, 8, 1, tzinfo=UTC),
        end=datetime(2013, 4, 1, tzinfo=UTC),
    )
    print(f"{DIM}{result.describe()}{OFF}\n")


def run_reference(*, trade_on_close: bool = True) -> dict[str, Any]:
    from backtesting import Backtest
    from backtesting.test import GOOG

    stats = Backtest(
        GOOG,
        reference_strategy(),
        cash=CASH,
        commission=float(COMMISSION_BPS) / 10_000,
        trade_on_close=trade_on_close,
        finalize_trades=False,
    ).run()
    trades = stats["_trades"]
    closed = trades[trades["ExitPrice"].notna()]
    return {
        "trades": len(closed),
        "win_rate": float(stats["Win Rate [%]"]),
        "closed_pnl": Decimal(str(round(float(closed["PnL"].sum()), 8))),
        "final_equity": Decimal(str(round(float(stats["Equity Final [$]"]), 8))),
        "total_return": Decimal(str(round(float(stats["Return [%]"]), 6))),
        "sharpe": Decimal(str(round(float(stats["Sharpe Ratio"]), 6))),
        "rows": closed,
    }


def run_ours(catalog_path: str) -> Any:
    from engine.backtest.request import BacktestRequest
    from engine.backtest.runner import execute
    from engine.data.sources.csv_file import _register_ticker
    from engine.settings import Settings

    _register_ticker("GOOG")
    request = BacktestRequest.model_validate(
        {
            "requestId": "req_compare",
            "strategyVersionId": "sv_compare",
            "spec": dsl_spec(),
            "venue": "NASDAQ",
            "instrumentId": "GOOG.NASDAQ",
            "barType": BAR_TYPE,
            "start": f"{START}T00:00:00Z",
            "end": f"{END}T00:00:00Z",
            "startingBalances": [f"{CASH} USD"],
            "fees": {"makerBps": COMMISSION_BPS, "takerBps": COMMISSION_BPS},
            "slippageBps": "0",
        }
    )
    settings = Settings(
        _env_file=None,
        catalog_path=catalog_path,
        internal_api_key="script",
        log_level="ERROR",
    )
    return execute(request, settings)


# --- presentation --------------------------------------------------------


def verdict(delta: Decimal, tolerance: Decimal) -> str:
    ok = abs(delta) <= tolerance
    return f"{GREEN}agree{OFF}" if ok else f"{RED}DIFFER{OFF}"


def show_summary(theirs: dict[str, Any], mine: Any) -> bool:
    """Print the comparison, separating what must agree from what cannot.

    Trade-level results and end-state values are computed the same way by both
    engines and must match. Risk statistics are computed from the *shape* of the
    equity curve, and the two engines draw that curve differently -- see below.
    """
    summary = mine.summary
    exact = [
        ("trades", Decimal(theirs["trades"]), Decimal(summary["tradeCount"]), Decimal(0)),
        ("win rate %", Decimal(str(theirs["win_rate"])), Decimal(summary["winRate"]), Decimal("0.01")),
        (
            "closed-trade PnL",
            theirs["closed_pnl"],
            sum((Decimal(t["pnl"]) for t in mine.trades), Decimal(0)),
            Decimal("0.10"),
        ),
        ("final equity", theirs["final_equity"], Decimal(summary["endingEquity"]), Decimal("0.10")),
        ("total return %", theirs["total_return"], Decimal(summary["totalReturn"]), Decimal("0.001")),
    ]
    path_dependent = [
        ("sharpe", theirs["sharpe"], Decimal(summary["sharpe"])),
    ]

    print(f"{BOLD}{'must agree':<20}{'backtesting.py':>18}{'this service':>18}{'delta':>14}   {OFF}")
    print("-" * 78)
    everything_agrees = True
    for label, expected, produced, tolerance in exact:
        delta = produced - expected
        if abs(delta) > tolerance:
            everything_agrees = False
        print(
            f"{label:<20}{expected:>18,.4f}{produced:>18,.4f}{delta:>14,.4f}   "
            f"{verdict(delta, tolerance)}"
        )

    print()
    print(f"{BOLD}{'differ by design':<20}{'backtesting.py':>18}{'this service':>18}{'delta':>14}   {OFF}")
    print("-" * 78)
    for label, expected, produced in path_dependent:
        print(f"{label:<20}{expected:>18,.4f}{produced:>18,.4f}{produced - expected:>14,.4f}")
    print(
        f"{DIM}Risk statistics come from the shape of the equity curve, not its endpoints.\n"
        f"This service's curve is realized: it steps when a trade closes. The reference\n"
        f"marks the open position every day, so its curve has motion between trades that\n"
        f"ours does not. Same start, same end, different path -- so the volatility of the\n"
        f"daily returns differs, and Sharpe with it. Max drawdown has the same cause.\n"
        f"A mark-to-market curve needs a portfolio valuation per bar; it is not built.{OFF}"
    )

    print()
    print(
        f"{DIM}open position at the end: {summary['openPositions']}, "
        f"marked to market at {summary['unrealizedPnl']}{OFF}"
    )
    return everything_agrees


def show_trades(theirs: dict[str, Any], mine: Any, limit: int) -> None:
    print()
    print(f"{BOLD}trade by trade{OFF}  (first {limit})")
    print(
        f"{'#':>3} {'their qty':>10} {'my qty':>8} {'their entry':>12} {'my entry':>10} "
        f"{'their exit':>11} {'my exit':>10} {'their PnL':>12} {'my PnL':>12}"
    )
    print("-" * 96)
    mismatches = 0
    for index in range(min(len(mine.trades), theirs["trades"])):
        expected = theirs["rows"].iloc[index]
        produced = mine.trades[index]
        same = (
            int(expected["Size"]) == int(Decimal(produced["quantity"]))
            and abs(float(expected["EntryPrice"]) - float(produced["entryPrice"])) < 0.005
            and abs(float(expected["ExitPrice"]) - float(produced["exitPrice"])) < 0.005
        )
        if not same:
            mismatches += 1
        if index < limit or not same:
            mark = "" if same else f"  {RED}<-- differs{OFF}"
            print(
                f"{index:>3} {int(expected['Size']):>10} {produced['quantity']:>8} "
                f"{expected['EntryPrice']:>12.2f} {produced['entryPrice']:>10} "
                f"{expected['ExitPrice']:>11.2f} {produced['exitPrice']:>10} "
                f"{expected['PnL']:>12.2f} {float(produced['pnl']):>12.2f}{mark}"
            )
    print()
    colour = GREEN if mismatches == 0 else RED
    print(
        f"{colour}{len(mine.trades) - mismatches} of {len(mine.trades)} trades identical"
        f"{OFF} on quantity, entry price and exit price"
    )


def show_fill_study(catalog_path: str) -> None:
    """What the fill-timing assumption is worth on this market."""
    print()
    print(f"{BOLD}what fill timing costs{OFF}  (docs/nautilus-api-notes.md D12)")
    print()
    next_open = run_reference(trade_on_close=False)
    on_close = run_reference(trade_on_close=True)
    mine = run_ours(catalog_path).summary

    print(f"{'':<18}{'fills next open':>18}{'fills on close':>18}{'this service':>16}")
    print("-" * 70)
    for label, key, ours_key in [
        ("win rate %", "win_rate", "winRate"),
        ("total return %", "total_return", "totalReturn"),
        ("sharpe", "sharpe", "sharpe"),
    ]:
        print(
            f"{label:<18}{float(next_open[key]):>18.4f}{float(on_close[key]):>18.4f}"
            f"{float(mine[ours_key]):>16.4f}"
        )
    cost = float(next_open["win_rate"]) - float(on_close["win_rate"])
    print()
    print(
        f"{DIM}Filling at the signal bar's close rather than the next bar's open costs\n"
        f"{cost:.1f} percentage points of win rate on daily equities. On BTCUSDT 15m the\n"
        f"same assumption is worth almost nothing: close[t] equals open[t+1] on 49% of\n"
        f"bars, with a median difference of 0.00001%. Equities gap overnight; crypto\n"
        f"does not.{OFF}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare this service against backtesting.py on one strategy.",
    )
    parser.add_argument("--trades", action="store_true", help="print the trades side by side")
    parser.add_argument("--limit", type=int, default=10, help="how many trades to print")
    parser.add_argument(
        "--fill-study", action="store_true", help="show what the fill-timing assumption costs"
    )
    parser.add_argument("--catalog", default="./catalog", help="catalog path")
    args = parser.parse_args(argv)

    if not FIXTURE.exists():
        print(f"{RED}missing reference data:{OFF} {FIXTURE}", file=sys.stderr)
        return 1

    import logging

    logging.getLogger("engine").setLevel(logging.ERROR)

    print()
    print(f"{BOLD}SMA({FAST}) x SMA({SLOW}) crossover on GOOG daily{OFF}")
    print(f"{DIM}{START} to {END}   ${CASH:,} starting   {COMMISSION_BPS} bps commission")
    print(f"long only on both sides; the reference fills on close, as this service does{OFF}")
    print()

    ensure_data(args.catalog)
    theirs = run_reference(trade_on_close=True)
    mine = run_ours(args.catalog)

    agreed = show_summary(theirs, mine)
    if args.trades:
        show_trades(theirs, mine, args.limit)
    if args.fill_study:
        show_fill_study(args.catalog)

    print()
    if agreed:
        print(f"{GREEN}{BOLD}The two engines agree on everything they compute the same way.{OFF}")
    else:
        print(f"{RED}{BOLD}The engines disagree beyond tolerance — investigate.{OFF}")
    print(f"{DIM}Write-up: docs/reproduction-sma-cross-goog.md{OFF}")
    print()
    return 0 if agreed else 1


if __name__ == "__main__":
    raise SystemExit(main())
