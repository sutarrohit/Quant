"""Phase 5 acceptance (spec section 10, ADR-001).

The phase built a recovery system. This is where it recovers from something.

Seven criteria:

* a ``SIGKILL`` runs no cleanup -- the premise everything else rests on;
* a node killed mid-position is detected and brought back **once**;
* recovery reconciles against the venue *before* it builds anything;
* a venue that disagrees halts the account, and the halt survives every
  subsequent pass;
* only an operator clears a halt;
* one node per account, across supervisors, even while one is dying;
* a kill switch engaged before the crash is still engaged after it.

**What is deliberately not asserted here.** Nautilus's own cache recovery --
rebuilding orders and positions from Redis -- is Nautilus's machinery, and
testing it would need a real Redis instance and a real venue, which ADR-001
forbids this repo from having. What is ours, and what is tested, is everything
around it: that an abrupt death is noticed, that exactly one node comes back,
that it does not come back trading on state the venue disagrees with, and that
a stop survives the process that was stopped.

The crash is a real one -- a real child process, a real ``SIGKILL``, no
handlers. What a ``SIGKILL`` leaves behind is then the starting state for the
rest, because that is precisely what a supervisor finds.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

import fakeredis
import fakeredis.aioredis
import pytest

from engine.errors import LiveNotPermitted, ReconciliationFailed
from engine.live.desired_state import (
    DesiredState,
    DesiredStatus,
    LiveStateStore,
    ObservedStatus,
    TradingMode,
)
from engine.live.kill_switch import CompositeKillSwitch, FileKillSwitch, RedisKillSwitch
from engine.live.node import LiveNodeRunner
from engine.live.recovery import AccountSnapshot, OrderSnapshot, PositionSnapshot
from engine.live.supervisor import Supervisor
from engine.settings import Settings
from tests.live.conftest import Clock, desired

#: The account is holding half a coin when the process dies. Every scenario
#: below starts from here, because a crash while flat is not the one that
#: matters -- a position with nobody managing its stop is.
POSITION = PositionSnapshot("BTCUSDT.BINANCE", Decimal("0.5"), "LONG")
HOLDING = AccountSnapshot(positions=(POSITION,))
FLAT = AccountSnapshot()


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "redis_url": "redis://localhost:6379/0",
        "cache_redis_url": "redis://localhost:6380/0",
        "internal_api_key": "x",
        "log_level": "ERROR",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


class Reader:
    def __init__(self, snapshot: AccountSnapshot) -> None:
        self._snapshot = snapshot

    async def snapshot(self, account_id: str) -> AccountSnapshot:
        return self._snapshot


class CountingRunner:
    """A node runner that counts starts and can be killed abruptly.

    ``crash()`` is what a ``SIGKILL`` does to this object's real counterpart:
    the node stops existing without anything being told.
    """

    def __init__(self) -> None:
        self.running: set[str] = set()
        self.starts = 0
        self.stops = 0

    async def start(self, state: DesiredState) -> None:
        self.starts += 1
        self.running.add(state.account_id)

    async def stop(self, account_id: str) -> None:
        self.stops += 1
        self.running.discard(account_id)

    async def is_running(self, account_id: str) -> bool:
        return account_id in self.running

    def crash(self, account_id: str) -> None:
        self.running.discard(account_id)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def redis_server() -> fakeredis.FakeServer:
    return fakeredis.FakeServer()


@pytest.fixture
def store(clock: Clock, redis_server: fakeredis.FakeServer) -> LiveStateStore:
    redis = fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True)
    return LiveStateStore(redis, lease_seconds=30, now=clock)


@pytest.fixture
def runner() -> CountingRunner:
    return CountingRunner()


@pytest.fixture
def supervisor(store: LiveStateStore, runner: CountingRunner, clock: Clock) -> Supervisor:
    return Supervisor(
        store, runner, holder="sup_a", heartbeat_timeout_seconds=90, now=clock
    )


async def running_account(
    store: LiveStateStore, supervisor: Supervisor, runner: CountingRunner
) -> DesiredState:
    """An account that is up and holding a position. The state before the crash."""
    state = await store.put(desired("acct_1"))
    await supervisor.reconcile_once()
    assert await runner.is_running("acct_1")
    return state


# --- 1. the premise: a SIGKILL runs no cleanup ---------------------------


CHILD = """
import os, signal, sys, time
from pathlib import Path

marker = Path(sys.argv[1])
heartbeat = Path(sys.argv[2])
try:
    heartbeat.write_text(str(time.time()))
    Path(sys.argv[3]).write_text("up")
    while True:
        time.sleep(0.01)
finally:
    # A clean shutdown would leave this. A SIGKILL must not.
    marker.write_text("cleanup ran")
"""


def test_a_sigkill_runs_no_cleanup(tmp_path: Path) -> None:
    """The premise of the whole phase.

    A supervisor exists because a node can stop without saying so. If a killed
    process still got to tidy up, its observed record would be accurate and
    none of the machinery below would be needed -- so this is worth asserting
    rather than assuming.
    """
    marker = tmp_path / "cleanup"
    heartbeat = tmp_path / "heartbeat"
    ready = tmp_path / "ready"

    child = subprocess.Popen(
        [sys.executable, "-c", CHILD, str(marker), str(heartbeat), str(ready)]
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "the child never started"

        os.kill(child.pid, signal.SIGKILL)
        assert child.wait(timeout=10) == -signal.SIGKILL
    finally:
        if child.poll() is None:  # pragma: no cover - only on an assertion above
            child.kill()

    assert not marker.exists(), "a SIGKILL must not run a finally block"
    # And the last heartbeat it wrote is now simply old. That, and nothing
    # else, is what the supervisor has to work from.
    assert heartbeat.exists()


# --- 2. a killed node is noticed, and comes back once --------------------


async def test_a_killed_node_is_restarted(
    store: LiveStateStore, supervisor: Supervisor, runner: CountingRunner, clock: Clock
) -> None:
    await running_account(store, supervisor, runner)

    runner.crash("acct_1")  # SIGKILL: nothing is written, nothing is told.
    clock.advance(91)  # The heartbeat stops being plausible.

    actions = await supervisor.reconcile_once()

    assert [action.action for action in actions] == ["restart"]
    assert await runner.is_running("acct_1")


async def test_the_record_still_says_running_after_the_kill(
    store: LiveStateStore, supervisor: Supervisor, runner: CountingRunner
) -> None:
    """The state a crash actually leaves: a lie, and a stale timestamp.

    Nothing marks itself dead. The only evidence is a heartbeat that stopped,
    which is why staleness rather than a status is what triggers recovery.
    """
    await running_account(store, supervisor, runner)

    runner.crash("acct_1")

    observed = await store.observed("acct_1")
    assert observed is not None
    assert observed.status is ObservedStatus.RUNNING


async def test_it_comes_back_exactly_once(
    store: LiveStateStore, supervisor: Supervisor, runner: CountingRunner, clock: Clock
) -> None:
    """Two nodes on one account is the worst outcome available.

    Each would believe it held the whole position, and each would manage a stop
    for it. Passes after the restart must find nothing to do.
    """
    await running_account(store, supervisor, runner)
    runner.crash("acct_1")
    clock.advance(91)

    await supervisor.reconcile_once()
    starts_after_recovery = runner.starts
    for _ in range(5):
        assert await supervisor.reconcile_once() == []

    assert starts_after_recovery == 2  # the original, and the one recovery made
    assert runner.starts == 2


async def test_a_live_node_is_left_alone(
    store: LiveStateStore, supervisor: Supervisor, runner: CountingRunner, clock: Clock
) -> None:
    # The opposite error: restarting a node that is merely quiet. It would
    # close a position that nothing was wrong with.
    await running_account(store, supervisor, runner)

    clock.advance(89)
    await store.heartbeat("acct_1")
    clock.advance(89)

    assert await supervisor.reconcile_once() == []
    assert runner.starts == 1


# --- 3. recovery reconciles before it builds anything --------------------


def node_runner(cached: AccountSnapshot, venue: AccountSnapshot) -> LiveNodeRunner:
    from engine.live.kill_switch import NeverEngaged

    redis = fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    return LiveNodeRunner(
        settings(),
        LiveStateStore(redis),
        kill_switch=NeverEngaged(),
        cache_reader=Reader(cached),
        venue_reader=Reader(venue),
    )


async def test_reconciliation_happens_before_the_node_is_built() -> None:
    """Spec section 10.3 fixes the order: cache, venue, compare, *then* start.

    Proven by which failure comes out. Live is gated by ADR-001, so a node that
    reached the build step raises ``LiveNotPermitted``; one that reconciled
    first and disagreed raises ``ReconciliationFailed``. Getting the second
    means nothing was built.
    """
    runner = node_runner(cached=FLAT, venue=HOLDING)

    with pytest.raises(ReconciliationFailed):
        await runner.start(desired(mode=TradingMode.LIVE, credential_ref="ref"))


async def test_an_agreeing_venue_gets_as_far_as_the_build() -> None:
    # The control for the test above: with nothing to disagree about,
    # reconciliation passes and the ADR-001 gate is what stops it.
    runner = node_runner(cached=HOLDING, venue=HOLDING)

    with pytest.raises(LiveNotPermitted):
        await runner.start(desired(mode=TradingMode.LIVE, credential_ref="ref"))


async def test_the_position_that_survived_the_crash_is_what_is_compared() -> None:
    """Recovery is only worth anything if it recovers the position.

    Cache and venue both hold the half coin the dead node was carrying, and
    they agree -- which is the case that is allowed to resume.
    """
    runner = node_runner(cached=HOLDING, venue=HOLDING)

    with pytest.raises(LiveNotPermitted):  # i.e. it got past reconciliation
        await runner.start(desired(mode=TradingMode.LIVE, credential_ref="ref"))


async def test_an_order_the_venue_kept_is_a_disagreement() -> None:
    # The subtler crash: the node died between submitting and recording. The
    # venue has a working order that our cache has never heard of.
    orphan = AccountSnapshot(
        positions=(POSITION,),
        orders=(OrderSnapshot("O-1", "BTCUSDT.BINANCE", "SELL", Decimal("0.5"), "ACCEPTED"),),
    )
    runner = node_runner(cached=HOLDING, venue=orphan)

    with pytest.raises(ReconciliationFailed, match="ORDER_ONLY_AT_VENUE"):
        await runner.start(desired(mode=TradingMode.LIVE, credential_ref="ref"))


# --- 4. a disagreement halts, and stays halted ---------------------------


class HaltingRunner(CountingRunner):
    async def start(self, state: DesiredState) -> None:
        self.starts += 1
        raise ReconciliationFailed(
            "the venue holds a position the cache does not",
            details={"discrepancies": [{"kind": "POSITION_ONLY_AT_VENUE"}]},
        )


async def test_a_disagreeing_venue_halts_the_account(
    store: LiveStateStore, clock: Clock
) -> None:
    runner = HaltingRunner()
    supervisor = Supervisor(store, runner, holder="sup_a", now=clock)
    await store.put(desired("acct_1"))

    actions = await supervisor.reconcile_once()

    assert [action.action for action in actions] == ["halted"]
    observed = await store.observed("acct_1")
    assert observed is not None
    assert observed.status is ObservedStatus.HALTED
    assert observed.status.needs_operator


async def test_a_halt_is_not_retried(store: LiveStateStore, clock: Clock) -> None:
    """A node that hammers the exchange every five seconds while wrong is not
    recovering. It is being wrong faster."""
    runner = HaltingRunner()
    supervisor = Supervisor(store, runner, holder="sup_a", now=clock)
    await store.put(desired("acct_1"))
    await supervisor.reconcile_once()
    starts_after_halt = runner.starts

    for _ in range(10):
        clock.advance(60)
        assert await supervisor.reconcile_once() == []

    assert runner.starts == starts_after_halt


async def test_a_halt_records_why(store: LiveStateStore, clock: Clock) -> None:
    # An operator has to be able to see what disagreed without a debugger.
    supervisor = Supervisor(store, HaltingRunner(), holder="sup_a", now=clock)
    await store.put(desired("acct_1"))

    await supervisor.reconcile_once()

    observed = await store.observed("acct_1")
    assert observed is not None
    assert observed.error is not None
    assert observed.error["code"] == "RECONCILIATION_FAILED"
    assert observed.error["discrepancies"] == [{"kind": "POSITION_ONLY_AT_VENUE"}]


# --- 5. only an operator clears a halt -----------------------------------


async def test_restating_the_desire_clears_a_halt(
    store: LiveStateStore, clock: Clock
) -> None:
    """The deliberate act. A new revision is an operator saying "I have looked
    at it" -- the one thing a supervisor cannot manufacture for itself."""
    runner = HaltingRunner()
    supervisor = Supervisor(store, runner, holder="sup_a", now=clock)
    await store.put(desired("acct_1"))
    await supervisor.reconcile_once()
    starts_after_halt = runner.starts

    await store.put(desired("acct_1"))  # the operator re-states it: revision 2

    await supervisor.reconcile_once()
    assert runner.starts == starts_after_halt + 1


async def test_a_halted_account_can_still_be_stopped(
    store: LiveStateStore, clock: Clock
) -> None:
    # Halted is not a trap. An operator who wants it gone gets it gone.
    supervisor = Supervisor(store, HaltingRunner(), holder="sup_a", now=clock)
    await store.put(desired("acct_1"))
    await supervisor.reconcile_once()

    await store.stop("acct_1")
    await supervisor.reconcile_once()

    observed = await store.observed("acct_1")
    assert observed is not None
    assert observed.status is ObservedStatus.STOPPED


# --- 6. one node per account, across supervisors -------------------------


async def test_a_second_supervisor_does_not_take_a_held_account(
    store: LiveStateStore, supervisor: Supervisor, runner: CountingRunner, clock: Clock
) -> None:
    await running_account(store, supervisor, runner)
    other_runner = CountingRunner()
    other = Supervisor(store, other_runner, holder="sup_b", now=clock)

    assert await other.reconcile_once() == []
    assert other_runner.starts == 0


async def test_a_dead_supervisors_account_is_taken_over(
    store: LiveStateStore, supervisor: Supervisor, runner: CountingRunner, clock: Clock
) -> None:
    """The supervisor process dies too, not just the node.

    Its lease is what keeps a second supervisor off the account, and a lease
    that outlived its holder would strand the account permanently. So it
    expires.
    """
    await running_account(store, supervisor, runner)
    runner.crash("acct_1")

    clock.advance(91)
    await store.release("acct_1", "sup_a")  # the lease TTL, reached

    other_runner = CountingRunner()
    other = Supervisor(store, other_runner, holder="sup_b", now=clock)
    actions = await other.reconcile_once()

    assert [action.action for action in actions] == ["restart"]
    assert other_runner.starts == 1
    assert await store.lease_holder("acct_1") == "sup_b"


async def test_two_supervisors_racing_produce_one_node(
    store: LiveStateStore, clock: Clock
) -> None:
    # Both pass at once over an account nothing is running. Exactly one wins.
    first, second = CountingRunner(), CountingRunner()
    await store.put(desired("acct_1"))

    results = await asyncio.gather(
        Supervisor(store, first, holder="sup_a", now=clock).reconcile_once(),
        Supervisor(store, second, holder="sup_b", now=clock).reconcile_once(),
    )

    assert sum(len(actions) for actions in results) == 1
    assert first.starts + second.starts == 1


# --- 7. a stop survives the process it stopped ---------------------------


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


async def test_a_kill_engaged_before_the_crash_is_still_engaged_after(
    redis_server: fakeredis.FakeServer, tmp_path: Path
) -> None:
    """The kill switch lives outside the process it stops.

    An operator who stopped an account and then watched the node die must not
    find it trading again a minute later because recovery lost the instruction.
    """
    from engine.live.worker import attach_gate

    redis = fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True)
    switch = CompositeKillSwitch(RedisKillSwitch(redis), FileKillSwitch(tmp_path))
    await RedisKillSwitch(redis).engage("acct_1")

    # The node dies and a new *process* is spawned. Nothing of the old one
    # remains -- not the gate, not the node, not the interpreter. The kill
    # switch outlives all of it because it was never in there.
    strategy = FakeStrategy()
    await attach_gate(FakeNode(strategy), desired("acct_1"), switch)

    assert strategy.risk_gate.kill_engaged is True  # type: ignore[attr-defined]


async def test_the_recovered_node_will_not_trade_on_a_gate_it_never_read(
    redis_server: fakeredis.FakeServer, tmp_path: Path
) -> None:
    """The window a restart opens, closed.

    A freshly built gate has never read its kill switch, and a gate that has
    never read one is stale by definition -- so an entry submitted between
    ``build()`` and the first refresh is refused rather than allowed.
    """
    from engine.live.gate import RiskGate
    from engine.live.risk import AccountRisk, Breach, OrderIntent

    never_refreshed = RiskGate(account_id="acct_1")

    decision = never_refreshed.check(
        OrderIntent("BTCUSDT.BINANCE", Decimal(100)), AccountRisk(), now_ns=0
    )

    assert not decision.allowed
    assert decision.breach is Breach.KILL_SWITCH


async def test_a_file_kill_survives_redis_being_unreachable(tmp_path: Path) -> None:
    """The path that works when the fast one does not.

    A crash that took Redis with it -- or a partition, or this service's API
    being wedged -- must not also take away the ability to stop an account.
    """

    class Unreachable:
        async def is_engaged(self, account_id: str) -> bool:
            raise ConnectionError("redis is gone")

    file_switch = FileKillSwitch(tmp_path)
    file_switch.engage("acct_1")

    assert await CompositeKillSwitch(Unreachable(), file_switch).is_engaged("acct_1")
    # And even with nothing engaged, an unreadable path is treated as a stop.
    assert await CompositeKillSwitch(Unreachable()).is_engaged("acct_2")


# --- the phase, end to end ----------------------------------------------


async def test_crash_recover_and_resume(
    store: LiveStateStore, runner: CountingRunner, clock: Clock
) -> None:
    """One account, from up to killed to back up, in the order it happens.

    Every step is asserted where a real operator would look: the stored record,
    not the object graph.
    """
    supervisor = Supervisor(store, runner, holder="sup_a", now=clock)

    # Up, holding a position.
    await store.put(desired("acct_1"))
    await supervisor.reconcile_once()
    first = await store.observed("acct_1")
    assert first is not None and first.status is ObservedStatus.RUNNING

    # kill -9. The record is now wrong and nothing knows it.
    runner.crash("acct_1")
    assert not await runner.is_running("acct_1")
    stale = await store.observed("acct_1")
    assert stale is not None and stale.status is ObservedStatus.RUNNING

    # The heartbeat stops being plausible, and the supervisor acts.
    clock.advance(91)
    assert [action.action for action in await supervisor.reconcile_once()] == ["restart"]

    # Back up, on the same revision, under one lease, and left alone after.
    recovered = await store.observed("acct_1")
    assert recovered is not None
    assert recovered.status is ObservedStatus.RUNNING
    assert recovered.revision == 1
    assert await store.lease_holder("acct_1") == "sup_a"
    assert await supervisor.reconcile_once() == []
    assert runner.starts == 2


async def test_the_operator_can_still_stop_it_afterwards(
    store: LiveStateStore, runner: CountingRunner, clock: Clock
) -> None:
    supervisor = Supervisor(store, runner, holder="sup_a", now=clock)
    await store.put(desired("acct_1"))
    await supervisor.reconcile_once()
    runner.crash("acct_1")
    clock.advance(91)
    await supervisor.reconcile_once()

    await store.stop("acct_1")
    await supervisor.reconcile_once()

    observed = await store.observed("acct_1")
    assert observed is not None
    assert observed.status is ObservedStatus.STOPPED
    desired_now = await store.get("acct_1")
    assert desired_now is not None and desired_now.status is DesiredStatus.STOPPED
    assert not await runner.is_running("acct_1")
