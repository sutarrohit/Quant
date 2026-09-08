"""Live control-plane fixtures."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

import fakeredis
import fakeredis.aioredis
import pytest

from engine.live.desired_state import DesiredState, LiveStateStore, TradingMode


class Clock:
    """Advances only when told, so heartbeat staleness is assertable."""

    def __init__(self) -> None:
        self.moment = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, seconds: int) -> None:
        self.moment += timedelta(seconds=seconds)


SPEC: dict[str, Any] = {
    "strategyId": "btc-rsi",
    "version": 1,
    "market": {
        "exchange": "binance",
        "marketType": "spot",
        "symbols": ["BTC/USDT"],
        "timeframe": "15m",
    },
    "entry": {"indicator": "rsi", "period": 14, "operator": "crossesAbove", "value": 30},
    "exit": {"any": [{"type": "stopLossPercent", "value": 2}]},
    "sizing": {"type": "riskPercent", "riskPercent": 1},
}


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(clock: Clock) -> LiveStateStore:
    redis = fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    return LiveStateStore(redis, lease_seconds=30, now=clock)


def desired(account_id: str = "acct_1", **overrides: Any) -> DesiredState:
    payload: dict[str, Any] = {
        "account_id": account_id,
        "venue": "BINANCE",
        "instrument_id": "BTCUSDT.BINANCE",
        "bar_type": "BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL",
        "spec": copy.deepcopy(SPEC),
        "strategy_version_id": "sv_1",
        "spec_hash": "abc123",
        "mode": TradingMode.SIMULATION,
        "fees": {"maker_bps": "1", "taker_bps": "10", "slippage_bps": "5"},
    }
    payload.update(overrides)
    return DesiredState(**payload)


class RecordingRunner:
    """Records what it was asked to do instead of running a TradingNode.

    The logic worth testing here is the reconciliation, not the engine.
    """

    def __init__(self) -> None:
        self.running: set[str] = set()
        self.calls: list[tuple[str, str]] = []
        self.fail_on_start = False

    async def start(self, state: DesiredState) -> None:
        self.calls.append(("start", state.account_id))
        if self.fail_on_start:
            raise RuntimeError("the venue refused the connection")
        self.running.add(state.account_id)

    async def stop(self, account_id: str) -> None:
        self.calls.append(("stop", account_id))
        self.running.discard(account_id)

    async def is_running(self, account_id: str) -> bool:
        return account_id in self.running

    async def stop_all(self) -> None:
        for account_id in list(self.running):
            await self.stop(account_id)


@pytest.fixture
def runner() -> RecordingRunner:
    return RecordingRunner()
