"""What a strategy reports on a live node, exercised in a real backtest.

The recorder is set on a built strategy, like the risk gate. A backtest leaves it
None, so these tests attach one by wrapping `on_start` -- the same instance the
engine built, with nothing patched inside the strategy.

Whichever catalog this checkout has: BTC is the Phase 0 one, SOL is what the
simulations trade.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from engine.live.publisher import EventRecorder
from engine.strategies.dsl_strategy import DslStrategy

CATALOG = Path("catalog")
CANDIDATES = [
    ("BTCUSDT.BINANCE", "BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL", "BTC/USDT"),
    ("SOLUSDT.BINANCE", "SOLUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL", "SOL/USDT"),
]
AVAILABLE = [c for c in CANDIDATES if (CATALOG / "data" / "bar" / c[1]).exists()]

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="needs a 15m catalog; run the ingest")


def spec(symbol: str) -> dict[str, Any]:
    return {
        "strategyId": "recorder-test",
        "version": 1,
        "market": {"exchange": "binance", "marketType": "spot", "symbols": [symbol], "timeframe": "15m"},
        "entry": {"all": [{"indicator": "rsi", "period": 14, "operator": "crossesAbove", "value": 30}]},
        "exit": {
            "any": [
                {"type": "stopLossPercent", "value": 2},
                {"type": "takeProfitPercent", "value": 2},
            ]
        },
        "sizing": {"type": "riskPercent", "riskPercent": 1},
    }


def run(recorder: EventRecorder | None, monkeypatch: pytest.MonkeyPatch) -> tuple[pd.DataFrame, Any]:
    """A January backtest. Returns the fills report and the strategy instance."""
    from nautilus_trader.backtest.config import (
        BacktestDataConfig,
        BacktestEngineConfig,
        BacktestRunConfig,
        BacktestVenueConfig,
    )
    from nautilus_trader.backtest.node import BacktestNode
    from nautilus_trader.config import ImportableStrategyConfig, LoggingConfig
    from nautilus_trader.model import Bar

    from engine.dsl.hashing import spec_hash
    from engine.types.dsl import StrategySpec

    instrument_id, bar_type, symbol = AVAILABLE[0]
    built: list[Any] = []
    original = DslStrategy.on_start

    def on_start(self: Any) -> None:
        self.recorder = recorder
        built.append(self)
        original(self)

    monkeypatch.setattr(DslStrategy, "on_start", on_start)

    config = BacktestRunConfig(
        engine=BacktestEngineConfig(
            strategies=[
                ImportableStrategyConfig(
                    strategy_path="engine.strategies.dsl_strategy:DslStrategy",
                    config_path="engine.strategies.dsl_strategy:DslStrategyConfig",
                    config={
                        "instrument_id": instrument_id,
                        "bar_type": bar_type,
                        "spec": spec(symbol),
                        "strategy_version_id": "sv_test",
                        "spec_hash": spec_hash(StrategySpec.model_validate(spec(symbol))),
                        "cost_bps": "15",
                    },
                )
            ],
            logging=LoggingConfig(log_level="ERROR"),
        ),
        venues=[
            BacktestVenueConfig(
                name="BINANCE", oms_type="NETTING", account_type="CASH", starting_balances=["10000 USDT"]
            )
        ],
        data=[
            BacktestDataConfig(
                catalog_path=str(CATALOG),
                data_cls=Bar,
                instrument_id=instrument_id,
                bar_types=[bar_type],
                start_time="2024-01-01",
                end_time="2024-02-01",
            )
        ],
        dispose_on_completion=False,
    )
    node = BacktestNode(configs=[config])
    node.run()
    engine = node.get_engines()[0]
    try:
        fills = engine.trader.generate_order_fills_report()
        return fills.drop(columns=["init_id"], errors="ignore"), built[0]
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def recorded() -> tuple[list[dict[str, Any]], dict[str, Any], pd.DataFrame]:
    with pytest.MonkeyPatch.context() as monkeypatch:
        recorder = EventRecorder(maxlen=100_000)
        fills, strategy = run(recorder, monkeypatch)
        return recorder.drain(), strategy.status(), fills


def kinds(events: list[dict[str, Any]]) -> set[str]:
    return {event["kind"] for event in events}


def test_a_trading_month_records_the_whole_story(recorded: Any) -> None:
    events, _, fills = recorded
    assert len(fills) > 0, "the spec should trade in January"

    assert {"SIGNAL", "ENTRY_SUBMITTED", "FILL", "POSITION_CLOSED"} <= kinds(events)
    assert sum(1 for e in events if e["kind"] == "FILL") == len(fills)


def test_a_fill_carries_its_fee_and_currency(recorded: Any) -> None:
    # The fee's currency is reported, never assumed (L5).
    events, _, _ = recorded
    fill = next(e for e in events if e["kind"] == "FILL")

    assert fill["side"] == "BUY"
    assert fill["tradeId"]
    assert fill["commission"]["currency"] == "USDT"
    assert float(fill["commission"]["amount"]) >= 0


def test_a_closed_position_reports_its_result(recorded: Any) -> None:
    events, _, _ = recorded
    closed = next(e for e in events if e["kind"] == "POSITION_CLOSED")

    assert closed["realizedPnl"]["currency"] == "USDT"
    assert closed["durationSeconds"] > 0
    assert closed["entryPrice"] and closed["exitPrice"]


def test_status_explains_the_rule_being_checked(recorded: Any) -> None:
    _, status, _ = recorded

    assert status["phase"] in {"WAITING_FOR_ENTRY", "IN_POSITION"}
    assert "2024-01-31" < status["lastBar"]["time"] <= "2024-02-01T00:00:00Z"  # The last bar closes at the end.
    evaluation = status["lastEvaluation"]
    assert evaluation["side"] in {"entry", "exit"}
    assert evaluation["conditions"], "each leaf of the rule, with whether it holds"
    assert all({"path", "label", "passed", "series"} <= set(c) for c in evaluation["conditions"])
    assert status["values"]["rsi:14"]


def test_recording_does_not_change_what_trades(
    recorded: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The recorder watches. A backtest with one must fill exactly as one without.
    _, _, with_recorder = recorded
    without, _ = run(None, monkeypatch)

    pd.testing.assert_frame_equal(with_recorder, without)
