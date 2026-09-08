"""Builder fixtures."""

from __future__ import annotations

from typing import Any

import pytest

from engine.backtest.request import BacktestRequest
from engine.settings import Settings

SPEC: dict[str, Any] = {
    "strategyId": "btc-rsi-recovery",
    "version": 4,
    "market": {
        "exchange": "binance",
        "marketType": "spot",
        "symbols": ["BTC/USDT"],
        "timeframe": "15m",
    },
    "entry": {"all": [{"indicator": "rsi", "period": 14, "operator": "crossesAbove", "value": 30}]},
    "exit": {
        "any": [
            {"type": "takeProfitPercent", "value": 4},
            {"type": "stopLossPercent", "value": 2},
        ]
    },
    "sizing": {"type": "riskPercent", "riskPercent": 1},
}

# The exact request shape from spec section 7.2.
REQUEST: dict[str, Any] = {
    "requestId": "req_01K000000000000000000000",
    "strategyVersionId": "sv_01K000000000000000000000",
    "spec": SPEC,
    "venue": "BINANCE",
    "instrumentId": "BTCUSDT.BINANCE",
    "barType": "BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL",
    "start": "2023-01-01T00:00:00Z",
    "end": "2025-01-01T00:00:00Z",
    "startingBalances": ["10000 USDT"],
    "fees": {"makerBps": "1", "takerBps": "10"},
    "slippageBps": "5",
}


@pytest.fixture
def request_dict() -> dict[str, Any]:
    import copy

    return copy.deepcopy(REQUEST)


@pytest.fixture
def backtest_request(request_dict: dict[str, Any]) -> BacktestRequest:
    return BacktestRequest.model_validate(request_dict)


@pytest.fixture
def builder_settings() -> Settings:
    return Settings(_env_file=None, catalog_path="./catalog", log_level="ERROR")
