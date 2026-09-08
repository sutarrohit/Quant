"""An independent replay of a DSL strategy. No Nautilus, no engine code.

Written from the rules rather than from the implementation, so that agreement
between this and the engine is evidence rather than tautology. It duplicates,
deliberately:

* Wilder's RSI, from its definition;
* the entry and exit decisions;
* position sizing from the risk budget;
* the fee and slippage arithmetic;
* fill prices and realized PnL.

Where it makes an assumption about the engine's behaviour -- that an order
fills at the signal bar's close, for instance -- the assumption is named, so a
disagreement points at a specific claim rather than at "something differs".
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal


@dataclass(frozen=True, slots=True)
class Candle:
    ts: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True, slots=True)
class ReplayTrade:
    entry_ts: int
    exit_ts: int
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    commission: Decimal
    pnl: Decimal


def wilder_rsi(closes: list[Decimal], period: int) -> list[float | None]:
    """Wilder's RSI on 0..100, unseeded, one value per bar.

    Unseeded because that is what Nautilus does: the average gain and loss
    start at zero and smooth in (docs/nautilus-api-notes.md D13). Computed in
    float, matching the engine -- this is indicator math, not money.
    """
    values: list[float | None] = [None]
    gain = loss = 0.0
    alpha = 1.0 / period

    for index in range(1, len(closes)):
        change = float(closes[index] - closes[index - 1])
        gain += alpha * (max(change, 0.0) - gain)
        loss += alpha * (max(-change, 0.0) - loss)
        rsi = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
        # The engine reports nothing until `period` bars have been seen.
        values.append(rsi * 1.0 if index >= period else None)
    return values


def floor_to(value: Decimal, increment: Decimal) -> Decimal:
    return (value / increment).to_integral_value(rounding=ROUND_DOWN) * increment


def replay(
    candles: list[Candle],
    *,
    rsi_period: int,
    entry_threshold: Decimal,
    take_profit_percent: Decimal,
    stop_loss_percent: Decimal,
    risk_percent: Decimal,
    fee_bps: Decimal,
    slippage_bps: Decimal,
    starting_equity: Decimal,
    size_increment: Decimal,
    min_notional: Decimal,
) -> list[ReplayTrade]:
    """Replay `rsi crossesAbove threshold` with percentage exits.

    Assumptions about the engine, each one testable on its own:

    1. A signal is decided on a closed bar and fills at **that bar's close**
       (D12), not the next bar's open.
    2. A crossing needs a previous value: it is False on the first bar with an
       RSI reading.
    3. Only one position is held at a time.
    4. Both legs pay ``notional x (fee_bps + slippage_bps) / 10_000``.
    5. Exits are evaluated before entries on a bar where a position is open,
       so a close and a re-entry cannot happen on the same bar.
    """
    closes = [candle.close for candle in candles]
    rsi = wilder_rsi(closes, rsi_period)

    trades: list[ReplayTrade] = []
    equity = starting_equity
    rate = (fee_bps + slippage_bps) / Decimal(10_000)

    open_qty: Decimal | None = None
    entry_price = Decimal(0)
    entry_ts = 0
    entry_commission = Decimal(0)

    for index, candle in enumerate(candles):
        current, previous = rsi[index], rsi[index - 1] if index else None
        if current is None:
            continue

        if open_qty is not None:
            move = (candle.close - entry_price) / entry_price * 100
            if move >= take_profit_percent or move <= -stop_loss_percent:
                exit_notional = open_qty * candle.close
                exit_commission = exit_notional * rate
                gross = open_qty * (candle.close - entry_price)
                pnl = gross - entry_commission - exit_commission
                equity += pnl
                trades.append(
                    ReplayTrade(
                        entry_ts=entry_ts,
                        exit_ts=candle.ts,
                        quantity=open_qty,
                        entry_price=entry_price,
                        exit_price=candle.close,
                        commission=entry_commission + exit_commission,
                        pnl=pnl,
                    )
                )
                open_qty = None
            continue

        crossed = previous is not None and previous <= float(entry_threshold) < current
        if not crossed:
            continue

        # equity x risk% / (price x stop%), floored to the venue step, and
        # never more than the balance can pay for.
        wanted = (equity * risk_percent) / (candle.close * stop_loss_percent)
        affordable = equity / candle.close
        quantity = floor_to(min(wanted, affordable), size_increment)
        if quantity <= 0 or quantity * candle.close < min_notional:
            continue

        open_qty = quantity
        entry_price = candle.close
        entry_ts = candle.ts
        entry_commission = quantity * candle.close * rate

    return trades
