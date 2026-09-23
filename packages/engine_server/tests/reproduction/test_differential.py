"""Phase 4: the engine against an independent replay (spec section 8).

The same strategy, implemented twice, over the same bars. Implementation A is
this service -- Nautilus, the DSL interpreter, the fee model, the results
module. Implementation B is `replay.py`: a few hundred lines of plain Python
written from the rules, with no engine code in it at all.

Agreement is evidence. Disagreement points at one of a small number of named
assumptions, which is what makes a delta explainable rather than merely
reported.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from engine.backtest.runner import execute
from engine.data.catalog import Catalog
from engine.settings import Settings
from engine.types.backtest import BacktestRequest
from tests.reproduction.replay import Candle, replay

BAR_TYPE = "BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL"
CATALOG = Path("catalog")

RSI_PERIOD = 14
ENTRY_THRESHOLD = Decimal(30)
TAKE_PROFIT = Decimal(4)
STOP_LOSS = Decimal(2)
RISK_PERCENT = Decimal(1)
FEE_BPS = Decimal(10)
SLIPPAGE_BPS = Decimal(5)
STARTING_EQUITY = Decimal(10_000)

# From exchangeInfo, the same values ingest wrote into the catalog.
SIZE_INCREMENT = Decimal("0.00001")
MIN_NOTIONAL = Decimal(5)

pytestmark = pytest.mark.skipif(
    not (CATALOG / "data" / "bar" / BAR_TYPE).exists(), reason="needs the Phase 0 catalog"
)

WINDOWS = [("2024-01-01", "2024-02-01"), ("2024-03-01", "2024-06-01"), ("2023-06-01", "2023-09-01")]


def spec() -> dict[str, Any]:
    return {
        "strategyId": "rsi-reproduction",
        "version": 1,
        "market": {
            "exchange": "binance",
            "marketType": "spot",
            "symbols": ["BTC/USDT"],
            "timeframe": "15m",
        },
        "entry": {
            "all": [
                {
                    "indicator": "rsi",
                    "period": RSI_PERIOD,
                    "operator": "crossesAbove",
                    "value": str(ENTRY_THRESHOLD),
                }
            ]
        },
        "exit": {
            "any": [
                {"type": "takeProfitPercent", "value": str(TAKE_PROFIT)},
                {"type": "stopLossPercent", "value": str(STOP_LOSS)},
            ]
        },
        "sizing": {"type": "riskPercent", "riskPercent": str(RISK_PERCENT)},
    }


def request_for(start: str, end: str) -> BacktestRequest:
    return BacktestRequest.model_validate(
        {
            "requestId": f"req_{start}_{end}",
            "strategyVersionId": "sv_reproduction",
            "spec": copy.deepcopy(spec()),
            "venue": "BINANCE",
            "instrumentId": "BTCUSDT.BINANCE",
            "barType": BAR_TYPE,
            "start": f"{start}T00:00:00Z",
            "end": f"{end}T00:00:00Z",
            "startingBalances": [f"{STARTING_EQUITY} USDT"],
            "fees": {"makerBps": "1", "takerBps": str(FEE_BPS)},
            "slippageBps": str(SLIPPAGE_BPS),
        }
    )


def settings() -> Settings:
    return Settings(
        _env_file=None, catalog_path="./catalog", internal_api_key="x", log_level="ERROR"
    )


def candles_for(request: BacktestRequest) -> list[Candle]:
    """The same bars the engine reads, in the same window."""
    start_ns = int(request.start.timestamp() * 1000) * 1_000_000
    end_ns = int(request.end.timestamp() * 1000) * 1_000_000
    bars = Catalog("./catalog").read_bars(BAR_TYPE, start=start_ns, end=end_ns)
    return [
        Candle(
            ts=bar.ts_event,
            open=bar.open.as_decimal(),
            high=bar.high.as_decimal(),
            low=bar.low.as_decimal(),
            close=bar.close.as_decimal(),
        )
        for bar in bars
    ]


def replay_for(request: BacktestRequest) -> list[Any]:
    return replay(
        candles_for(request),
        rsi_period=RSI_PERIOD,
        entry_threshold=ENTRY_THRESHOLD,
        take_profit_percent=TAKE_PROFIT,
        stop_loss_percent=STOP_LOSS,
        risk_percent=RISK_PERCENT,
        fee_bps=FEE_BPS,
        slippage_bps=SLIPPAGE_BPS,
        starting_equity=STARTING_EQUITY,
        size_increment=SIZE_INCREMENT,
        min_notional=MIN_NOTIONAL,
    )


@pytest.mark.parametrize(("start", "end"), WINDOWS)
def test_the_two_implementations_take_the_same_trades(start: str, end: str) -> None:
    request = request_for(start, end)
    engine = execute(request, settings())
    reference = replay_for(request)

    assert len(reference) > 3, "a window with too few trades proves little"
    assert engine.closed_positions == len(reference), (
        f"engine closed {engine.closed_positions} positions, replay took {len(reference)}"
    )


@pytest.mark.parametrize(("start", "end"), WINDOWS)
def test_every_trade_agrees_on_prices_and_quantity(start: str, end: str) -> None:
    """Exact equality on the values a venue would have printed.

    Prices are quantized to the instrument's tick (D14), so this compares the
    price the exchange traded at rather than a float approximation of it.
    """
    request = request_for(start, end)
    engine = execute(request, settings()).trades
    reference = replay_for(request)

    for index, (produced, expected) in enumerate(zip(engine, reference, strict=True)):
        assert Decimal(produced["entryPrice"]) == expected.entry_price, f"trade {index} entry"
        assert Decimal(produced["exitPrice"]) == expected.exit_price, f"trade {index} exit"
        assert Decimal(produced["quantity"]) == expected.quantity, f"trade {index} quantity"


@pytest.mark.parametrize(("start", "end"), WINDOWS)
def test_every_trade_agrees_on_pnl(start: str, end: str) -> None:
    """Within float epsilon, not a modelling tolerance.

    Both sides compute ``quantity x (exit - entry)`` less commission on the
    same numbers. They differ only in the order the arithmetic is accumulated,
    which lands around 1e-8 on values near 150. Anything larger would mean the
    two are modelling different things.
    """
    request = request_for(start, end)
    engine = execute(request, settings()).trades
    reference = replay_for(request)

    for index, (produced, expected) in enumerate(zip(engine, reference, strict=True)):
        delta = abs(Decimal(produced["pnl"]) - expected.pnl)
        assert delta < Decimal("0.000001"), f"trade {index} PnL differs by {delta}"

    total_engine = sum(Decimal(trade["pnl"]) for trade in engine)
    total_reference = sum(trade.pnl for trade in reference)
    assert abs(total_engine - total_reference) < Decimal("0.0001")


@pytest.mark.parametrize(("start", "end"), WINDOWS)
def test_costs_agree(start: str, end: str) -> None:
    # The fee model is ours; the replay charges the same rate from the rules.
    request = request_for(start, end)
    engine = execute(request, settings()).trades
    reference = replay_for(request)

    for produced, expected in zip(engine, reference, strict=True):
        assert abs(Decimal(produced["commission"]) - expected.commission) < Decimal("0.000001")


def test_prices_carry_no_float_artefacts() -> None:
    """Rule 4: money is Decimal end to end.

    Nautilus's positions report returns prices as floats, so an average that
    should be 44622.99 arrives as 44622.990000000005. Quantizing to the
    instrument's tick keeps that out of the stored trade table (D14).
    """
    engine = execute(request_for("2024-01-01", "2024-02-01"), settings()).trades

    for trade in engine:
        for field in ("entryPrice", "exitPrice"):
            value = Decimal(trade[field])
            assert -value.as_tuple().exponent <= 2, f"{field}={value} carries float error"

