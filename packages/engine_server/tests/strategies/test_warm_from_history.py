"""A restarted live node warms its indicators from past bars instead of waiting."""

from __future__ import annotations

from typing import Any

from nautilus_trader.model import Bar, BarType
from nautilus_trader.model.objects import Price, Quantity

from engine.strategies.config import strategy_config
from engine.strategies.dsl_strategy import DslStrategy, DslStrategyConfig

BAR_TYPE = "SOLUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL"
FIFTEEN_MIN_NS = 900_000_000_000
START_NS = 1_790_000_000_000_000_000

SPEC: dict[str, Any] = {
    "strategyId": "warm",
    "version": 1,
    "market": {"exchange": "binance", "marketType": "spot", "symbols": ["SOL/USDT"], "timeframe": "15m"},
    "entry": {"all": [{"indicator": "rsi", "period": 14, "operator": "crossesAbove", "value": 30}]},
    "exit": {"any": [{"type": "stopLossPercent", "value": 2}]},
    "sizing": {"type": "riskPercent", "riskPercent": 1},
}


def bar(n: int, close: str = "100") -> Bar:
    ts = START_NS + n * FIFTEEN_MIN_NS
    price = Price.from_str(close)
    return Bar(BarType.from_str(BAR_TYPE), price, price, price, price, Quantity.from_str("1"), ts, ts)


def strategy() -> DslStrategy:
    built = DslStrategy(
        DslStrategyConfig(
            instrument_id="SOLUSDT.BINANCE",
            bar_type=BAR_TYPE,
            spec=SPEC,
            strategy_version_id="sv",
            spec_hash="h",
        )
    )
    built.warm_from_history = True
    built._series = built._build_series()  # What on_start does, without a running node.
    return built


def test_past_bars_warm_every_indicator_without_trading() -> None:
    warm = strategy()

    for n in range(warm.warmup_bars + 2):
        warm._warm(bar(n, str(100 + n % 3)))

    assert all(series.initialized for series in warm._series.values())
    assert "rsi:14" in warm._previous  # The first live bar can already see a crossing.
    assert warm.bars_from_history == warm.bars_seen == warm.warmup_bars + 2
    assert warm.orders_submitted == 0


def test_a_bar_older_than_one_already_seen_is_dropped() -> None:
    # A live bar can beat the history back; older bars must not follow it in.
    warm = strategy()
    warm._warm(bar(5))

    warm._warm(bar(3))
    warm._warm(bar(5))

    assert warm.bars_from_history == 1


def test_a_backtest_never_asks_for_history() -> None:
    # Off unless a live worker turns it on; the config carries no trace of it.
    built = DslStrategy(
        DslStrategyConfig(instrument_id="SOLUSDT.BINANCE", bar_type=BAR_TYPE, spec=SPEC, strategy_version_id="sv", spec_hash="h")
    )
    config = strategy_config(
        instrument_id="SOLUSDT.BINANCE", bar_type=BAR_TYPE, spec=SPEC, strategy_version_id="sv", spec_hash="h"
    ).config

    assert built.warm_from_history is False
    assert "warm_from_history" not in config


def test_a_live_worker_turns_it_on() -> None:
    from engine.live.worker import attach_recorder
    from tests.live.test_worker import FakeNode, FakeStrategy

    strategy = FakeStrategy()
    strategy.warm_from_history = False  # type: ignore[attr-defined]
    strategy.recorder = None  # type: ignore[attr-defined]

    attach_recorder(FakeNode(strategy))

    assert strategy.warm_from_history is True  # type: ignore[attr-defined]
