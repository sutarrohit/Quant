"""Fixtures for DSL tests."""

from __future__ import annotations

from typing import Any

import pytest

# The exact example from spec section 5.1. Kept verbatim so a schema change
# that breaks the documented shape fails here.
SPEC_EXAMPLE: dict[str, Any] = {
    "strategyId": "btc-rsi-recovery",
    "version": 4,
    "market": {
        "exchange": "binance",
        "marketType": "spot",
        "symbols": ["BTC/USDT"],
        "timeframe": "15m",
    },
    "entry": {
        "all": [
            {"indicator": "rsi", "period": 14, "operator": "crossesAbove", "value": 30},
            {"indicator": "volume", "operator": "greaterThanSma", "period": 20},
        ]
    },
    "exit": {
        "any": [
            {"type": "takeProfitPercent", "value": 4},
            {"type": "stopLossPercent", "value": 2},
            {"indicator": "rsi", "period": 14, "operator": "greaterThan", "value": 70},
        ]
    },
    "sizing": {"type": "riskPercent", "riskPercent": 1},
}


@pytest.fixture
def spec_dict() -> dict[str, Any]:
    import copy

    return copy.deepcopy(SPEC_EXAMPLE)


def nested(depth: int) -> dict[str, Any]:
    """A condition tree nested `depth` groups deep with one leaf at the bottom."""
    node: dict[str, Any] = {"indicator": "rsi", "period": 14, "operator": "greaterThan", "value": 70}
    for _ in range(depth - 1):
        node = {"all": [node]}
    return node


def leaves(count: int) -> dict[str, Any]:
    """A single group holding `count` leaves."""
    return {
        "all": [
            {"indicator": "rsi", "period": 2 + index, "operator": "greaterThan", "value": 70}
            for index in range(count)
        ]
    }
