"""Fixtures for strategy tests.

The backtest fixtures need the Phase 0 catalog. Tests that use them skip when it
is absent, so the suite stays runnable on a fresh clone.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

CATALOG = Path("catalog")
BAR_TYPE = "BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL"
INSTRUMENT_ID = "BTCUSDT.BINANCE"

requires_catalog = pytest.mark.skipif(
    not (CATALOG / "data" / "bar" / BAR_TYPE).exists(),
    reason="needs the Phase 0 catalog; run `python -m engine.data.ingest`",
)


@pytest.fixture
def rsi_spec() -> dict[str, Any]:
    return {
        "strategyId": "btc-rsi-recovery",
        "version": 1,
        "market": {
            "exchange": "binance",
            "marketType": "spot",
            "symbols": ["BTC/USDT"],
            "timeframe": "15m",
        },
        "entry": {"all": [{"indicator": "rsi", "period": 14, "operator": "crossesAbove", "value": 30}]},
        "exit": {
            "any": [
                {"type": "stopLossPercent", "value": 2},
                {"indicator": "rsi", "period": 14, "operator": "greaterThan", "value": 70},
            ]
        },
        "sizing": {"type": "riskPercent", "riskPercent": 1},
    }


def run_backtest(
    spec: dict[str, Any],
    *,
    start: str = "2024-01-01",
    end: str = "2024-02-01",
    log_level: str = "DEBUG",
) -> list[dict[str, Any]]:
    """Run a real BacktestNode and return this strategy's structured log records."""
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
    from engine.logging import configure_logging
    from engine.types.dsl import StrategySpec

    stream = io.StringIO()
    configure_logging(log_level, stream=stream)

    config = BacktestRunConfig(
        engine=BacktestEngineConfig(
            strategies=[
                ImportableStrategyConfig(
                    strategy_path="engine.strategies.dsl_strategy:DslStrategy",
                    config_path="engine.strategies.dsl_strategy:DslStrategyConfig",
                    config={
                        "instrument_id": INSTRUMENT_ID,
                        "bar_type": BAR_TYPE,
                        "spec": spec,
                        "strategy_version_id": "sv_test",
                        "spec_hash": spec_hash(StrategySpec.model_validate(spec)),
                    },
                )
            ],
            logging=LoggingConfig(log_level="ERROR"),
        ),
        venues=[
            BacktestVenueConfig(
                name="BINANCE",
                oms_type="NETTING",
                account_type="CASH",
                starting_balances=["10000 USDT"],
            )
        ],
        data=[
            BacktestDataConfig(
                catalog_path=str(CATALOG),
                data_cls=Bar,
                instrument_id=INSTRUMENT_ID,
                bar_types=[BAR_TYPE],
                start_time=start,
                end_time=end,
            )
        ],
    )
    BacktestNode(configs=[config]).run()

    return [
        json.loads(line)
        for line in stream.getvalue().splitlines()
        if line.startswith("{") and "dsl_strategy" in line
    ]


def signals(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if record["message"] == "signal fired"]


def evaluations(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if record["message"] == "signal evaluated"]


#: The only non-deterministic column in a fills report: a UUID4 minted per
#: order-initialized event. See docs/nautilus-api-notes.md D9.
NON_DETERMINISTIC_COLUMNS = ["init_id"]


def run_backtest_reports(
    spec: dict[str, Any],
    *,
    start: str = "2024-01-01",
    end: str = "2024-03-01",
    starting_balances: list[str] | None = None,
) -> dict[str, Any]:
    """Run a backtest and return its reports.

    ``dispose_on_completion=False`` because it defaults to True and clears the
    cache before ``run()`` returns, which makes every report come back empty.
    The engine is disposed here instead, after extraction (spec section 7.4).
    """
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

    config = BacktestRunConfig(
        engine=BacktestEngineConfig(
            strategies=[
                ImportableStrategyConfig(
                    strategy_path="engine.strategies.dsl_strategy:DslStrategy",
                    config_path="engine.strategies.dsl_strategy:DslStrategyConfig",
                    config={
                        "instrument_id": INSTRUMENT_ID,
                        "bar_type": BAR_TYPE,
                        "spec": spec,
                        "strategy_version_id": "sv_test",
                        "spec_hash": spec_hash(StrategySpec.model_validate(spec)),
                    },
                )
            ],
            logging=LoggingConfig(log_level="ERROR"),
        ),
        venues=[
            BacktestVenueConfig(
                name="BINANCE",
                oms_type="NETTING",
                account_type="CASH",
                starting_balances=starting_balances or ["10000 USDT"],
            )
        ],
        data=[
            BacktestDataConfig(
                catalog_path=str(CATALOG),
                data_cls=Bar,
                instrument_id=INSTRUMENT_ID,
                bar_types=[BAR_TYPE],
                start_time=start,
                end_time=end,
            )
        ],
        dispose_on_completion=False,
    )

    node = BacktestNode(configs=[config])
    node.run()
    engine = node.get_engines()[0]
    try:
        return {
            "fills": engine.trader.generate_order_fills_report(),
            "orders": engine.trader.generate_orders_report(),
            "positions": engine.trader.generate_positions_report(),
        }
    finally:
        # Nautilus engines hold a lot of memory; a leaking worker OOMs.
        engine.dispose()
