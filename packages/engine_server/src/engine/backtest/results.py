"""Backtest metrics and series (spec section 7.5).

Pure functions over the reports a run produced. No I/O, no clock: the same
fills always produce the same summary, which is what makes the golden-file test
meaningful.

**Money is ``Decimal`` throughout.** Ratios and risk statistics -- Sharpe,
Sortino, win rate -- are computed in ``float`` because they involve square
roots and are not money; they are quantized before they leave, so the output is
stable.

**The equity curve is realized, not mark-to-market.** It steps at each position
close rather than revaluing an open position every bar. That is exact and
deterministic from the reports alone; a mark-to-market curve needs a portfolio
valuation per bar, which Phase 4 can add if reproducing a published result
demands it. Every metric derived here says which curve it came from.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from engine.backtest.fees import split_cost
from engine.types.results import EquityPoint, Summary, Trade

#: Crypto trades every day, so a year is 365 days rather than 252.
TRADING_DAYS_PER_YEAR = 365

#: Places kept on ratios, so a summary is byte-stable across machines.
RATIO_PLACES = Decimal("0.000001")
MONEY_PLACES = Decimal("0.00000001")


def _q(value: Decimal | float, places: Decimal = RATIO_PLACES) -> Decimal:
    return Decimal(str(value)).quantize(places)


def _money(value: Any) -> Decimal:
    """Parse a Money cell, which may be a list, a string, or already numeric."""
    total = Decimal(0)
    for item in value if isinstance(value, list) else [value]:
        text = str(item)
        if text and text not in ("nan", "None"):
            total += Decimal(text.split()[0])
    return total


def _price(value: Any, precision: int | None) -> Decimal:
    """A price as the venue quotes it, not as a float rounds it."""
    price = Decimal(str(value))
    if precision is None:
        return price
    return price.quantize(Decimal(1).scaleb(-precision))


def _time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    # Nanosecond integers appear in some columns.
    return datetime.fromtimestamp(int(value) / 1e9, tz=UTC)


def build_trades(
    positions: Any,
    *,
    fee_bps: Decimal,
    slippage_bps: Decimal,
    price_precision: int | None = None,
) -> list[Trade]:
    """Closed positions as trades, with each one's costs split.

    Fees and slippage are both charged as commission proportional to notional
    (see ``backtest.fees``), so the split is exact arithmetic rather than an
    estimate: each is ``notional x bps / 10_000``.

    ``price_precision`` quantizes the prices. Nautilus returns them as floats
    in the positions report, so an average that should be ``44622.99`` arrives
    as ``44622.990000000005`` -- float error leaking into a field that is meant
    to be exact (D14). The venue trades on a tick, and that tick is the
    precision the price should carry.
    """
    if len(positions) == 0:
        return []

    closed = positions[positions["avg_px_close"].notna()]
    trades: list[Trade] = []

    for _, row in closed.iterrows():
        quantity = Decimal(str(row["peak_qty"]))
        entry_price = _price(row["avg_px_open"], price_precision)
        exit_price = _price(row["avg_px_close"], price_precision)
        commission = _money(row["commissions"])

        # Both legs are charged, so the notional that produced the commission
        # is entry plus exit.
        notional = quantity * entry_price + quantity * exit_price
        fees, slippage = split_cost(notional, fee_bps, slippage_bps)

        pnl = _money(row["realized_pnl"])
        holding = int(float(row["duration_ns"]) / 1e9)

        trades.append(
            Trade(
                entry_time=_time(row["ts_opened"]),
                exit_time=_time(row["ts_closed"]),
                side=str(row["entry"]),
                quantity=quantity,
                entry_price=entry_price,
                exit_price=exit_price,
                pnl=pnl,
                return_pct=_q((pnl / (quantity * entry_price)) * 100) if quantity else Decimal(0),
                commission=commission,
                fees=_q(fees, MONEY_PLACES),
                slippage=_q(slippage, MONEY_PLACES),
                holding_seconds=holding,
            )
        )
    return trades


def build_equity_curve(trades: list[Trade], starting_equity: Decimal) -> list[EquityPoint]:
    """Realized equity after each closed trade, with running drawdown."""
    equity = starting_equity
    peak = starting_equity
    points: list[EquityPoint] = []

    for trade in trades:
        equity += trade.pnl
        peak = max(peak, equity)
        drawdown = (equity - peak) / peak * 100 if peak > 0 else Decimal(0)
        points.append(EquityPoint(trade.exit_time, equity, _q(drawdown)))
    return points


def _daily_returns(points: list[EquityPoint], starting_equity: Decimal) -> list[float]:
    """Daily returns from the realized curve.

    Bucketed by day and forward-filled, so Sharpe is the conventional
    daily-return statistic rather than a per-trade one, and therefore
    comparable with a published figure.
    """
    if not points:
        return []

    by_day: dict[Any, Decimal] = {}
    for point in points:
        by_day[point.time.date()] = point.equity

    first = min(by_day)
    last = max(by_day)
    returns: list[float] = []
    previous = starting_equity
    day = first
    while day <= last:
        equity = by_day.get(day, previous)
        if previous > 0:
            returns.append(float((equity - previous) / previous))
        previous = equity
        day += timedelta(days=1)
    return returns


def _sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    if variance <= 0:
        return 0.0
    return mean / math.sqrt(variance) * math.sqrt(TRADING_DAYS_PER_YEAR)


def _sortino(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    downside = [value for value in returns if value < 0]
    if not downside:
        return 0.0
    deviation = math.sqrt(sum(value**2 for value in downside) / len(returns))
    if deviation <= 0:
        return 0.0
    return mean / deviation * math.sqrt(TRADING_DAYS_PER_YEAR)


def summarise(
    trades: list[Trade],
    equity_curve: list[EquityPoint],
    *,
    starting_equity: Decimal,
    start: datetime,
    end: datetime,
    unrealized_pnl: Decimal = Decimal(0),
    open_positions: int = 0,
) -> Summary:
    """The numbers section 7.5 asks for.

    ``unrealized_pnl`` marks a position still open on the last bar to that
    bar's close. Ending equity is realized profit *plus* that, so the figure is
    the account's actual worth rather than only the part that has been booked.
    Measured against backtesting.py on a trend-following strategy, omitting it
    understated the return by 77 percentage points, because such a strategy is
    usually still holding when the data ends.
    """
    realized = equity_curve[-1].equity if equity_curve else starting_equity
    ending = realized + unrealized_pnl
    total_return = (ending - starting_equity) / starting_equity * 100 if starting_equity else Decimal(0)

    window_seconds = max((end - start).total_seconds(), 1)
    years = window_seconds / (TRADING_DAYS_PER_YEAR * 24 * 3600)
    if starting_equity > 0 and ending > 0 and years > 0:
        cagr = (float(ending / starting_equity) ** (1 / years) - 1) * 100
    else:
        cagr = 0.0

    pnls: list[Decimal] = [trade.pnl for trade in trades]
    wins: list[Decimal] = [value for value in pnls if value > 0]
    losses: list[Decimal] = [value for value in pnls if value < 0]
    gross_profit: Decimal = sum(wins, Decimal(0))
    gross_loss: Decimal = abs(sum(losses, Decimal(0)))

    ordered: list[Decimal] = sorted(pnls)
    median: Decimal
    if ordered:
        middle = len(ordered) // 2
        median = (
            ordered[middle]
            if len(ordered) % 2
            else (ordered[middle - 1] + ordered[middle]) / 2
        )
    else:
        median = Decimal(0)

    exposure = sum(trade.holding_seconds for trade in trades)
    returns = _daily_returns(equity_curve, starting_equity)

    return Summary(
        starting_equity=_q(starting_equity, MONEY_PLACES),
        ending_equity=_q(ending, MONEY_PLACES),
        total_return=_q(total_return),
        cagr=_q(cagr),
        max_drawdown=_q(min((point.drawdown for point in equity_curve), default=Decimal(0))),
        sharpe=_q(_sharpe(returns)),
        sortino=_q(_sortino(returns)),
        win_rate=_q(Decimal(len(wins)) / len(pnls) * 100) if pnls else Decimal(0),
        profit_factor=_q(gross_profit / gross_loss) if gross_loss > 0 else Decimal(0),
        trade_count=len(trades),
        average_trade=_q(sum(pnls, Decimal(0)) / len(pnls), MONEY_PLACES) if pnls else Decimal(0),
        median_trade=_q(median, MONEY_PLACES),
        average_holding_seconds=int(exposure / len(trades)) if trades else 0,
        total_fees=_q(sum((trade.fees for trade in trades), Decimal(0)), MONEY_PLACES),
        total_slippage=_q(sum((trade.slippage for trade in trades), Decimal(0)), MONEY_PLACES),
        exposure_percent=_q(Decimal(exposure) / Decimal(str(window_seconds)) * 100),
        unrealized_pnl=_q(unrealized_pnl, MONEY_PLACES),
        open_positions=open_positions,
    )
