"""What one account's child process does.

`engine.live.worker` is the half of the runtime that moved across a process
boundary when isolation was fixed: the gate, the heartbeat, and the node
itself. It is tested here in-process -- called directly rather than spawned --
because a spawned child cannot share a fake Redis, and what is worth asserting
is the logic, not `multiprocessing`.

`tests/live/test_node.py` covers the parent's side: spawning, terminating, and
what happens when a child ignores SIGTERM.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

import fakeredis
import fakeredis.aioredis
import pytest

from engine.live.desired_state import LiveStateStore
from engine.live.gate import RiskGate
from engine.live.kill_switch import CompositeKillSwitch, FileKillSwitch, NeverEngaged
from engine.live.worker import attach_gate, build_kill_switch, tend
from engine.settings import Settings
from engine.types.state import RiskLimitsModel
from tests.live.conftest import desired


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "redis_url": "redis://localhost:6379/0",
        "cache_redis_url": "redis://localhost:6380/0",
        "internal_api_key": "x",
        "log_level": "ERROR",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


class FakeStrategy:
    def __init__(self) -> None:
        self.risk_gate: object | None = None


class FakeTrader:
    def __init__(self, *strategies: FakeStrategy) -> None:
        self._strategies = strategies

    def strategies(self) -> tuple[FakeStrategy, ...]:
        return self._strategies


class FakeNode:
    def __init__(self, *strategies: FakeStrategy) -> None:
        self.trader = FakeTrader(*strategies)


class Engaged:
    async def is_engaged(self, account_id: str) -> bool:
        return True


# --- the gate reaches the strategies -------------------------------------


async def test_every_strategy_on_a_node_shares_one_gate() -> None:
    """Limits are account-level.

    Five strategies each inside a per-strategy limit is one bet at five times
    the size, which is the failure `Quant-Phase.md` names.
    """
    first, second = FakeStrategy(), FakeStrategy()

    await attach_gate(FakeNode(first, second), desired(), NeverEngaged())

    assert first.risk_gate is second.risk_gate
    assert first.risk_gate is not None


async def test_a_gate_is_refreshed_before_the_node_runs() -> None:
    # Otherwise there is a window in which a strategy submits against a gate
    # that has never read its kill switch.
    strategy = FakeStrategy()

    gate = await attach_gate(FakeNode(strategy), desired(), NeverEngaged())

    assert gate.last_refresh_ns is not None


async def test_a_fresh_gate_passes_against_the_strategys_clock() -> None:
    # Refreshed from the worker, checked with the strategy's LiveClock: both must
    # be Unix ns. A monotonic stamp read as 56 years stale and blocked every entry.
    from nautilus_trader.common.component import LiveClock

    from engine.types.risk import AccountRisk, OrderIntent

    gate = await attach_gate(FakeNode(FakeStrategy()), desired(), NeverEngaged())
    decision = gate.check(
        OrderIntent(instrument_id="SOLUSDT.BINANCE", notional=Decimal("100"), reduce_only=False),
        AccountRisk(),
        LiveClock().timestamp_ns(),
    )

    assert decision.allowed, decision.reason


async def test_an_engaged_kill_switch_is_seen_at_attach_time() -> None:
    gate = await attach_gate(FakeNode(FakeStrategy()), desired(), Engaged())

    assert gate.kill_engaged is True


async def test_the_accounts_limits_reach_its_gate() -> None:
    state = desired().model_copy(
        update={"risk": RiskLimitsModel(max_order_notional=Decimal(5_000))}
    )

    gate = await attach_gate(FakeNode(FakeStrategy()), state, NeverEngaged())

    assert gate.limits.max_order_notional == Decimal(5_000)


# --- the kill switch the child builds ------------------------------------


def test_the_child_builds_a_composite_kill_switch(tmp_path: Path) -> None:
    """The child builds its own, from settings, rather than inheriting one.

    Nothing unpicklable crosses a spawn boundary, so a switch cannot be handed
    over -- and a child that quietly ended up with one path would be a kill
    switch that stops working on the day that path is the broken one.
    """
    redis = fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)

    switch = build_kill_switch(settings(live_kill_switch_dir=str(tmp_path)), redis)

    assert isinstance(switch, CompositeKillSwitch)
    assert any(isinstance(path, FileKillSwitch) for path in switch._switches)  # noqa: SLF001


# --- the tending loop ----------------------------------------------------


@pytest.fixture
def store() -> LiveStateStore:
    redis = fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    return LiveStateStore(redis)


async def run_briefly(coro: object, seconds: float = 0.06) -> None:
    task = asyncio.create_task(coro)  # type: ignore[arg-type]
    await asyncio.sleep(seconds)
    task.cancel()


async def test_tending_keeps_the_gate_fresh(store: LiveStateStore) -> None:
    """The refresh rides the heartbeat deliberately.

    If that task dies the gate goes stale, which stops new orders, *and* the
    heartbeat stops, which brings the supervisor. One failure, both responses.
    """
    gate = RiskGate(account_id="acct_1")

    await run_briefly(
        tend(
            gate,
            NeverEngaged(),
            store,
            "acct_1",
            heartbeat_seconds=0.05,
            kill_switch_seconds=0.01,
        )
    )

    assert gate.last_refresh_ns is not None


async def test_a_kill_engaged_after_start_is_picked_up(store: LiveStateStore) -> None:
    class Flips:
        def __init__(self) -> None:
            self.engaged = False

        async def is_engaged(self, account_id: str) -> bool:
            return self.engaged

    switch = Flips()
    gate = RiskGate(account_id="acct_1")
    switch.engaged = True

    await run_briefly(
        tend(
            gate, switch, store, "acct_1", heartbeat_seconds=0.05, kill_switch_seconds=0.01
        ),
        seconds=0.03,
    )

    assert gate.kill_engaged is True


async def test_the_kill_switch_is_read_more_often_than_the_heartbeat(
    store: LiveStateStore,
) -> None:
    """An operator's stop must not wait a whole heartbeat interval.

    The heartbeat proves liveness on its own cadence; the kill switch is read
    on the shorter one.
    """

    class Counting:
        def __init__(self) -> None:
            self.reads = 0

        async def is_engaged(self, account_id: str) -> bool:
            self.reads += 1
            return False

    switch = Counting()

    await run_briefly(
        tend(
            RiskGate(account_id="acct_1"),
            switch,
            store,
            "acct_1",
            heartbeat_seconds=1.0,
            kill_switch_seconds=0.01,
        )
    )

    # Several reads inside one heartbeat interval, and no heartbeat yet.
    assert switch.reads >= 3
    assert await store.observed("acct_1") is None


# --- authority, in the child ---------------------------------------------


async def test_a_live_start_without_a_mandate_refuses() -> None:
    """Absent is not permissive (ADR-002).

    Trading real money with no recorded authority is worse than not trading,
    and "there was no record" is not a defence anyone wants to give afterwards.
    """
    from engine.live.mandate import MandateMissing, MandateStore
    from engine.live.worker import _authority
    from engine.types.state import TradingMode

    redis = fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)

    with pytest.raises(MandateMissing):
        await _authority(desired(mode=TradingMode.LIVE, credential_ref="ref"), MandateStore(redis))


async def test_a_simulation_needs_no_mandate() -> None:
    """A mandate authorises money; a simulation has none to authorise.

    Requiring one would put a control-plane step in front of the mode whose
    whole purpose is being easy to run.
    """
    from engine.live.mandate import MandateStore
    from engine.live.worker import _authority

    redis = fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)

    assert await _authority(desired(), MandateStore(redis)) is None


async def test_a_simulation_applies_a_mandate_that_exists() -> None:
    # So the path is exercised rather than dormant until the day it matters.
    from engine.live.mandate import Mandate, MandateStore
    from engine.live.worker import _authority

    redis = fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    store = MandateStore(redis)
    await store.put(Mandate(account_id="acct_1", mandate_id="m_1", issued_by="trading-core"))

    found = await _authority(desired(), store)

    assert found is not None and found.mandate_id == "m_1"


async def test_a_revocation_reaches_a_running_node(store: LiveStateStore) -> None:
    """Read, never pushed.

    `trading-core` writes to this service's store and the node reads it, which
    is why a `trading-core` outage cannot stop trading -- and why a revocation
    issued during one does not arrive. That cost is ADR-002's, and the kill
    switch is what covers it.
    """
    from engine.live.mandate import Mandate, MandateStore

    redis = fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    mandates = MandateStore(redis)
    await mandates.put(Mandate(account_id="acct_1", mandate_id="m_1", issued_by="trading-core"))
    gate = RiskGate(account_id="acct_1")

    await mandates.revoke("acct_1", by="an operator")
    await run_briefly(
        tend(
            gate,
            NeverEngaged(),
            store,
            "acct_1",
            heartbeat_seconds=0.05,
            kill_switch_seconds=0.01,
            mandates=mandates,
        ),
        seconds=0.03,
    )

    assert gate.mandate_revoked is True


async def test_an_unreadable_mandate_does_not_stop_trading(store: LiveStateStore) -> None:
    """The opposite of the kill switch, and deliberately so.

    A kill switch that cannot be read is treated as engaged, because an
    operator who cannot be heard must not be assumed to have said nothing. A
    mandate that cannot be read is *not* treated as withdrawn: authority
    already granted stands until someone removes it, and failing closed here
    would stop trading on a Redis blip -- the outcome ADR-002 exists to prevent.
    """

    class Unreadable:
        async def get(self, account_id: str) -> object:
            raise ConnectionError("redis is gone")

    gate = RiskGate(account_id="acct_1")

    await run_briefly(
        tend(
            gate,
            NeverEngaged(),
            store,
            "acct_1",
            heartbeat_seconds=0.05,
            kill_switch_seconds=0.01,
            mandates=Unreadable(),  # type: ignore[arg-type]
        ),
        seconds=0.03,
    )

    assert gate.mandate_revoked is False
