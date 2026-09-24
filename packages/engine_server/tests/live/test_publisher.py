"""The node's second channel: snapshot, events and equity, as JSON in Redis."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import fakeredis
import fakeredis.aioredis
import pytest
from nautilus_trader.model.enums import PositionSide
from nautilus_trader.model.objects import Currency, Money

from engine.live.publisher import (
    Baseline,
    EventRecorder,
    StateFeed,
    StatePublisher,
    build_snapshot,
)
from engine.types.state import TradingMode
from tests.live.conftest import desired

USDT, SOL, BTC = Currency.from_str("USDT"), Currency.from_str("SOL"), Currency.from_str("BTC")
NOW = 1_790_000_000_000_000_000


class FakeInstrument:
    quote_currency = USDT
    base_currency = SOL


class FakeAccount:
    def __init__(self, **balances: str) -> None:
        self._balances = {Currency.from_str(c): Money(Decimal(a), Currency.from_str(c)) for c, a in balances.items()}

    def balances_total(self) -> dict[Currency, Money]:
        return self._balances

    def balance_free(self, currency: Currency) -> Money:
        return self._balances[currency]

    def balance_locked(self, currency: Currency) -> Money:
        return Money(0, currency)


class FakePosition:
    side = PositionSide.LONG
    ts_opened = NOW - 3_600_000_000_000

    def __init__(self, quantity: str, avg_px_open: str) -> None:
        self.quantity = Decimal(quantity)
        self.avg_px_open = Decimal(avg_px_open)


class FakeCache:
    def __init__(self, account: FakeAccount, positions: list[FakePosition] | None = None) -> None:
        self.account = account
        self.positions = positions or []

    def instrument(self, instrument_id: object) -> FakeInstrument:
        return FakeInstrument()

    def account_for_venue(self, venue: object) -> FakeAccount:
        return self.account

    def positions_open(self, instrument_id: object = None) -> list[FakePosition]:
        return self.positions

    def orders_open(self, instrument_id: object = None) -> list[object]:
        return []


def status(close: str | None = None, bar_time: str = "2026-09-24T04:15:00Z") -> dict[str, Any]:
    return {
        "phase": "IN_POSITION",
        "lastBar": {"time": bar_time, "close": close} if close else None,
        "stopLossPercent": "2",
        "takeProfitPercent": "4",
    }


def sol_state() -> Any:
    return desired(
        "sim_1",
        instrument_id="SOLUSDT.BINANCE",
        bar_type="SOLUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL",
    )


def snapshot(cache: FakeCache, strategy: dict[str, Any] | None, **kw: Any) -> dict[str, Any]:
    return build_snapshot(
        kw.pop("state", sol_state()),
        cache,
        strategy,
        baseline=kw.pop("baseline", Baseline("USDT", Decimal(10_000), "2026-09-24T00:00:00Z")),
        now_ns=NOW,
        session_started_at="2026-09-24T00:00:00Z",
        kill_engaged=False,
        mandate_revoked=False,
    )


# --- the snapshot ------------------------------------------------------------


def test_a_flat_account_is_worth_its_cash() -> None:
    snap = snapshot(FakeCache(FakeAccount(USDT="10000")), status())

    assert snap["equity"] == "10000"
    assert snap["pnl"] == "0"
    assert snap["position"] is None
    assert [b["currency"] for b in snap["balances"]] == ["USDT"]


def test_a_held_position_is_valued_at_the_last_close() -> None:
    # The round trip measured on the running stack: bought 1.74 SOL @ 114.91.
    cache = FakeCache(FakeAccount(USDT="9799.75668490", SOL="1.74"), [FakePosition("1.74", "114.91")])
    snap = snapshot(cache, status(close="115.91"))

    equity = Decimal("9799.75668490") + Decimal("1.74") * Decimal("115.91")
    assert Decimal(snap["equity"]) == equity
    assert Decimal(snap["unrealizedPnl"]) == Decimal("1.74")
    assert Decimal(snap["pnl"]) == equity - 10_000
    assert Decimal(snap["realizedPnl"]) == equity - 10_000 - Decimal("1.74")  # The buy's fee.
    assert Decimal(snap["returnPercent"]) == (Decimal(snap["pnl"]) / 100).quantize(Decimal("0.00000001"))
    assert snap["unrealizedPnl"] == "1.74"  # Plain text, never "1.7400E+0".
    position = snap["position"]
    assert position["side"] == "LONG"
    assert Decimal(position["stopPrice"]) == Decimal("114.91") * Decimal("0.98")
    assert Decimal(position["takeProfitPrice"]) == Decimal("114.91") * Decimal("1.04")


def test_pnl_is_measured_from_the_baseline_not_nautilus() -> None:
    # Nautilus's realised P&L loses a reopened position's history on restart (D27).
    baseline = Baseline("USDT", Decimal("9999.487"), "2026-09-24T00:00:00Z")

    snap = snapshot(FakeCache(FakeAccount(USDT="9999.187")), status(), baseline=baseline)

    assert (snap["pnl"], snap["realizedPnl"], snap["unrealizedPnl"]) == ("-0.3", "-0.3", "0")


def test_before_a_baseline_there_is_no_pnl() -> None:
    snap = snapshot(FakeCache(FakeAccount(USDT="10000")), status(), baseline=None)

    assert (snap["pnl"], snap["returnPercent"]) == (None, None)


def test_equity_counts_only_the_instruments_currencies() -> None:
    # A real account holds coins the strategy never touched (L4).
    snap = snapshot(FakeCache(FakeAccount(USDT="10000", BTC="0.5")), status())

    assert snap["equity"] == "10000"
    assert [h["currency"] for h in snap["otherHoldings"]] == ["BTC"]


def test_without_a_price_a_held_coin_is_valued_at_entry() -> None:
    cache = FakeCache(FakeAccount(USDT="9800", SOL="1.74"), [FakePosition("1.74", "114.91")])

    snap = snapshot(cache, None)

    assert Decimal(snap["equity"]) == Decimal("9800") + Decimal("1.74") * Decimal("114.91")


def test_no_credential_reference_reaches_the_snapshot() -> None:
    # Built from an allowlist, never by dumping the desired state (L8).
    state = desired("acct_live", mode=TradingMode.LIVE, credential_ref="vault:binance/acct_live")

    snap = snapshot(FakeCache(FakeAccount(USDT="10000")), status(), state=state)

    assert "vault:" not in json.dumps(snap)
    assert snap["mode"] == "LIVE"


# --- the recorder ------------------------------------------------------------


def test_a_full_recorder_drops_the_oldest() -> None:
    recorder = EventRecorder(maxlen=2)
    for n in range(3):
        recorder.record("SIGNAL", NOW, n=n)

    assert [e["n"] for e in recorder.drain()] == [1, 2]


def test_undelivered_events_go_back_in_order() -> None:
    recorder = EventRecorder()
    recorder.record("A", NOW)
    failed = recorder.drain()
    recorder.record("B", NOW)

    recorder.put_back(failed)

    assert [e["kind"] for e in recorder.drain()] == ["A", "B"]


# --- writing and reading -----------------------------------------------------


class FakeStrategy:
    def __init__(self) -> None:
        self.state = status(close="115.91")

    def status(self) -> dict[str, Any]:
        return self.state


class FakeTrader:
    def __init__(self, strategy: FakeStrategy) -> None:
        self._strategy = strategy

    def strategies(self) -> list[FakeStrategy]:
        return [self._strategy]


class FakeNode:
    def __init__(self, usdt: str = "10000") -> None:
        self.cache = FakeCache(FakeAccount(USDT=usdt))
        self.strategy = FakeStrategy()
        self.trader = FakeTrader(self.strategy)


@pytest.fixture
def redis() -> Any:
    return fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)


async def test_a_tick_writes_the_snapshot_and_its_events(redis: Any) -> None:
    publisher = StatePublisher(redis, sol_state(), FakeNode(), EventRecorder())
    publisher.note("NODE_STARTED", revision=3)

    await publisher.publish()

    feed = StateFeed(redis)
    snap = await feed.snapshot("sim_1")
    assert snap is not None and snap["equity"] == "10000"
    events, last = await feed.events("sim_1", after=None, limit=10)
    assert [(e["kind"], e["revision"]) for e in events] == [("NODE_STARTED", 3)]
    assert last == events[0]["id"]


async def test_the_first_baseline_survives_a_restart(redis: Any) -> None:
    # Recorded once and kept (L2): a restart must not re-base the return.
    await StatePublisher(redis, sol_state(), FakeNode("10000"), EventRecorder()).publish()
    await StatePublisher(redis, sol_state(), FakeNode("9000"), EventRecorder()).publish()

    snap = await StateFeed(redis).snapshot("sim_1")

    assert snap is not None
    assert snap["baseline"]["amount"] == "10000"
    assert snap["equity"] == "9000"


async def test_the_first_snapshot_starts_the_pnl_at_zero(redis: Any) -> None:
    await StatePublisher(redis, sol_state(), FakeNode("9999.487"), EventRecorder()).publish()

    snap = await StateFeed(redis).snapshot("sim_1")
    assert snap is not None
    assert (snap["pnl"], snap["returnPercent"]) == ("0", "0")


async def test_one_equity_point_per_bar(redis: Any) -> None:
    node = FakeNode()
    publisher = StatePublisher(redis, sol_state(), node, EventRecorder())

    await publisher.publish()
    await publisher.publish()  # Same bar: no second point.
    node.strategy.state = status(close="116", bar_time="2026-09-24T04:30:00Z")
    await publisher.publish()

    points, _ = await StateFeed(redis).equity("sim_1", after=None)
    assert [p["time"] for p in points] == ["2026-09-24T04:15:00Z", "2026-09-24T04:30:00Z"]


async def test_events_page_forward_from_a_cursor(redis: Any) -> None:
    recorder = EventRecorder()
    publisher = StatePublisher(redis, sol_state(), FakeNode(), recorder)
    for n in range(5):
        recorder.record("SIGNAL", NOW, n=n)
    await publisher.flush_events()
    feed = StateFeed(redis)

    latest, _ = await feed.events("sim_1", after=None, limit=2)
    assert [e["n"] for e in latest] == [3, 4]  # The latest two, oldest first.

    first, cursor = await feed.events("sim_1", after="0-0", limit=2)
    rest, end = await feed.events("sim_1", after=cursor, limit=10)
    assert [e["n"] for e in first + rest] == [0, 1, 2, 3, 4]

    nothing, same = await feed.events("sim_1", after=end, limit=10)
    assert nothing == [] and same == end


async def test_a_failed_write_keeps_its_events(redis: Any) -> None:
    recorder = EventRecorder()
    publisher = StatePublisher(redis, sol_state(), FakeNode(), recorder)
    recorder.record("FILL", NOW)
    publisher._redis = _Failing()

    with pytest.raises(ConnectionError):
        await publisher.flush_events()

    assert [e["kind"] for e in recorder.drain()] == ["FILL"]


class _Failing:
    def pipeline(self) -> Any:
        return self

    def xadd(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def execute(self) -> None:
        raise ConnectionError("redis is down")
