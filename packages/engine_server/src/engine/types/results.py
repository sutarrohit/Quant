"""What a finished backtest is made of (spec section 7.5).

Money is ``Decimal`` throughout; ratios are computed in ``float`` and quantized
before they leave. `backtest/results.py` holds the functions that build these.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class Trade:
    """One round trip, with its costs attributed."""

    entry_time: datetime
    exit_time: datetime
    side: str
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    pnl: Decimal
    return_pct: Decimal
    commission: Decimal
    fees: Decimal
    slippage: Decimal
    holding_seconds: int

    def to_row(self) -> dict[str, Any]:
        return {
            "entryTime": self.entry_time.isoformat(),
            "exitTime": self.exit_time.isoformat(),
            "side": self.side,
            "quantity": str(self.quantity),
            "entryPrice": str(self.entry_price),
            "exitPrice": str(self.exit_price),
            "pnl": str(self.pnl),
            "returnPct": str(self.return_pct),
            "commission": str(self.commission),
            "fees": str(self.fees),
            "slippage": str(self.slippage),
            "holdingSeconds": self.holding_seconds,
        }


@dataclass(frozen=True, slots=True)
class EquityPoint:
    time: datetime
    equity: Decimal
    drawdown: Decimal

    def to_row(self) -> dict[str, Any]:
        return {
            "time": self.time.isoformat(),
            "equity": str(self.equity),
            "drawdown": str(self.drawdown),
        }


@dataclass(frozen=True, slots=True)
class Summary:
    """The numbers spec section 7.5 asks for."""

    starting_equity: Decimal
    ending_equity: Decimal
    total_return: Decimal
    cagr: Decimal
    max_drawdown: Decimal
    sharpe: Decimal
    sortino: Decimal
    win_rate: Decimal
    profit_factor: Decimal
    trade_count: int
    average_trade: Decimal
    median_trade: Decimal
    average_holding_seconds: int
    total_fees: Decimal
    total_slippage: Decimal
    exposure_percent: Decimal
    #: Value of a position still open on the last bar, marked to its close.
    #: Excluding it understates a trend follower badly -- such a strategy is
    #: usually holding when the data runs out.
    unrealized_pnl: Decimal = Decimal(0)
    open_positions: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "startingEquity": str(self.starting_equity),
            "endingEquity": str(self.ending_equity),
            "totalReturn": str(self.total_return),
            "cagr": str(self.cagr),
            "maxDrawdown": str(self.max_drawdown),
            "sharpe": str(self.sharpe),
            "sortino": str(self.sortino),
            "winRate": str(self.win_rate),
            "profitFactor": str(self.profit_factor),
            "tradeCount": self.trade_count,
            "averageTrade": str(self.average_trade),
            "medianTrade": str(self.median_trade),
            "averageHoldingSeconds": self.average_holding_seconds,
            "totalFees": str(self.total_fees),
            "totalSlippage": str(self.total_slippage),
            "exposurePercent": str(self.exposure_percent),
            "unrealizedPnl": str(self.unrealized_pnl),
            "openPositions": self.open_positions,
        }
