"""The reconciliation loop.

Each test names a gap between what should be running and what is, and asserts
the pass closes it. The runner is a recorder rather than a TradingNode: the
logic worth testing here is the reconciliation.
"""

from __future__ import annotations

import pytest

from engine.live.desired_state import (
    LiveStateStore,
    ObservedStatus,
)
from engine.live.supervisor import Supervisor
from tests.live.conftest import Clock, RecordingRunner, desired


@pytest.fixture
def supervisor(store: LiveStateStore, runner: RecordingRunner, clock: Clock) -> Supervisor:
    return Supervisor(store, runner, holder="supervisor-a", heartbeat_timeout_seconds=90, now=clock)


# --- the four gaps -------------------------------------------------------


async def test_wanted_running_and_nothing_is(
    store: LiveStateStore, supervisor: Supervisor, runner: RecordingRunner
) -> None:
    await store.put(desired())

    actions = await supervisor.reconcile_once()

    assert [a.action for a in actions] == ["start"]
    assert "acct_1" in runner.running
    observed = await store.observed("acct_1")
    assert observed is not None and observed.status is ObservedStatus.RUNNING


async def test_wanted_stopped_and_it_is_running(
    store: LiveStateStore, supervisor: Supervisor, runner: RecordingRunner
) -> None:
    await store.put(desired())
    await supervisor.reconcile_once()
    await store.stop("acct_1")

    actions = await supervisor.reconcile_once()

    assert [a.action for a in actions] == ["stop"]
    assert "acct_1" not in runner.running


async def test_running_an_older_revision(
    store: LiveStateStore, supervisor: Supervisor, runner: RecordingRunner
) -> None:
    # A spec change takes effect by restarting the node, which is what the
    # revision exists to detect.
    await store.put(desired())
    await supervisor.reconcile_once()
    await store.put(desired(strategy_version_id="sv_2"))

    actions = await supervisor.reconcile_once()

    assert [a.action for a in actions] == ["restart"]
    assert "wanted 2" in actions[0].reason
    observed = await store.observed("acct_1")
    assert observed is not None and observed.revision == 2


async def test_running_but_not_heartbeating(
    store: LiveStateStore, supervisor: Supervisor, runner: RecordingRunner, clock: Clock
) -> None:
    # A node holding a position with nobody managing its stop is the worst
    # state the system can be in, so the supervisor acts rather than waits.
    await store.put(desired())
    await supervisor.reconcile_once()
    clock.advance(600)

    actions = await supervisor.reconcile_once()

    assert [a.action for a in actions] == ["restart"]
    assert "heartbeating" in actions[0].reason


async def test_a_healthy_account_is_left_alone(
    store: LiveStateStore, supervisor: Supervisor, clock: Clock
) -> None:
    await store.put(desired())
    await supervisor.reconcile_once()
    clock.advance(10)
    assert await supervisor.reconcile_once() == []


async def test_the_record_disagreeing_with_the_runner_forces_a_restart(
    store: LiveStateStore, supervisor: Supervisor, runner: RecordingRunner, clock: Clock
) -> None:
    # The runner is closer to the truth than the record.
    await store.put(desired())
    await supervisor.reconcile_once()
    runner.running.discard("acct_1")

    # A node that vanished this quickly counts as a failed start, so the first
    # pass defers rather than restarting -- which is what stops a crash loop.
    assert await supervisor.reconcile_once() == []
    clock.advance(10)
    actions = await supervisor.reconcile_once()

    assert [a.action for a in actions] == ["restart"]
    assert "acct_1" in runner.running


# --- failure does not stop the loop --------------------------------------


async def test_a_node_that_cannot_start_is_recorded_not_raised(
    store: LiveStateStore, supervisor: Supervisor, runner: RecordingRunner
) -> None:
    runner.fail_on_start = True
    await store.put(desired())

    actions = await supervisor.reconcile_once()

    assert [a.action for a in actions] == ["start_failed"]
    observed = await store.observed("acct_1")
    assert observed is not None
    assert observed.status is ObservedStatus.FAILED
    assert observed.error is not None
    assert observed.error["code"] == "RuntimeError"


async def test_one_account_failing_does_not_abandon_the_others(
    store: LiveStateStore, supervisor: Supervisor, runner: RecordingRunner
) -> None:
    class SelectivelyBroken(RecordingRunner):
        async def start(self, state: object) -> None:
            if getattr(state, "account_id", "") == "acct_1":
                raise RuntimeError("nope")
            await RecordingRunner.start(self, state)  # type: ignore[arg-type]

    broken = SelectivelyBroken()
    supervisor._runner = broken  # noqa: SLF001
    await store.put(desired("acct_1"))
    await store.put(desired("acct_2"))

    actions = await supervisor.reconcile_once()

    assert {a.account_id: a.action for a in actions} == {
        "acct_1": "start_failed",
        "acct_2": "start",
    }
    assert "acct_2" in broken.running


async def test_a_failed_node_is_retried_after_its_backoff(
    store: LiveStateStore, supervisor: Supervisor, runner: RecordingRunner, clock: Clock
) -> None:
    # Every pass re-derives what to do, so a failure costs one backoff and
    # nothing else. It is deferred, never abandoned.
    runner.fail_on_start = True
    await store.put(desired())
    await supervisor.reconcile_once()
    runner.fail_on_start = False

    assert await supervisor.reconcile_once() == []
    clock.advance(10)
    actions = await supervisor.reconcile_once()

    assert [a.action for a in actions] == ["start"]
    assert "acct_1" in runner.running


# --- the lease -----------------------------------------------------------


async def test_an_account_held_elsewhere_is_left_alone(
    store: LiveStateStore, supervisor: Supervisor, runner: RecordingRunner
) -> None:
    await store.put(desired())
    await store.acquire("acct_1", "another-supervisor")

    assert await supervisor.reconcile_once() == []
    assert runner.calls == []


async def test_two_supervisors_start_one_node(
    store: LiveStateStore, runner: RecordingRunner, clock: Clock
) -> None:
    """The property a POST could never give.

    Two supervisors, one account: exactly one starts it. Without the lease both
    would, and each node would believe it held the whole position.
    """
    first = Supervisor(store, runner, holder="supervisor-a", now=clock)
    second = Supervisor(store, runner, holder="supervisor-b", now=clock)
    await store.put(desired())

    actions = await first.reconcile_once() + await second.reconcile_once()

    assert [a.action for a in actions] == ["start"]
    assert runner.calls == [("start", "acct_1")]


async def test_stopping_releases_the_lease(
    store: LiveStateStore, supervisor: Supervisor
) -> None:
    await store.put(desired())
    await supervisor.reconcile_once()
    await store.stop("acct_1")
    await supervisor.reconcile_once()

    assert await store.lease_holder("acct_1") is None


# --- a stopped account stays stopped -------------------------------------


async def test_a_stopped_account_is_not_restarted(
    store: LiveStateStore, supervisor: Supervisor, runner: RecordingRunner
) -> None:
    await store.put(desired())
    await supervisor.reconcile_once()
    await store.stop("acct_1")
    await supervisor.reconcile_once()

    assert await supervisor.reconcile_once() == []
    assert "acct_1" not in runner.running


async def test_an_account_with_no_record_is_ignored(
    store: LiveStateStore, supervisor: Supervisor
) -> None:
    await store.put(desired())
    await store.forget("acct_1")
    assert await supervisor.reconcile_once() == []


async def test_reconciliation_is_idempotent(
    store: LiveStateStore, supervisor: Supervisor, runner: RecordingRunner
) -> None:
    # A pass that changes nothing must change nothing, however often it runs.
    await store.put(desired())
    await supervisor.reconcile_once()
    before = list(runner.calls)

    for _ in range(5):
        assert await supervisor.reconcile_once() == []

    assert runner.calls == before


# --- a disagreement with the venue halts, it does not retry ---------------


class DisagreeingRunner(RecordingRunner):
    """A node that cannot agree with the venue about what it holds."""

    async def start(self, state: object) -> None:
        from decimal import Decimal

        from engine.live.recovery import (
            AccountSnapshot,
            PositionSnapshot,
            ReconciliationFailed,
            reconcile,
        )

        self.calls.append(("start", getattr(state, "account_id", "")))
        venue = AccountSnapshot(
            positions=(PositionSnapshot("BTCUSDT.BINANCE", Decimal("0.5"), "LONG"),)
        )
        result = reconcile(AccountSnapshot(), venue)
        raise ReconciliationFailed("disagrees with the venue", details=result.to_dict())


async def test_a_disagreement_halts_rather_than_failing(
    store: LiveStateStore, clock: Clock
) -> None:
    """Spec section 10.3.

    Crashing is a fact about the process and restarting is the right answer.
    Disagreeing with the venue is a fact about the money, and restarting into
    the same disagreement is not recovery.
    """
    runner = DisagreeingRunner()
    supervisor = Supervisor(store, runner, holder="supervisor-a", now=clock)
    await store.put(desired())

    actions = await supervisor.reconcile_once()

    assert [a.action for a in actions] == ["halted"]
    observed = await store.observed("acct_1")
    assert observed is not None
    assert observed.status is ObservedStatus.HALTED
    assert observed.error is not None
    assert observed.error["code"] == "RECONCILIATION_FAILED"


async def test_a_halted_account_is_not_retried(store: LiveStateStore, clock: Clock) -> None:
    # A node hammering the exchange every five seconds while wrong is not
    # recovering; it is being wrong faster.
    runner = DisagreeingRunner()
    supervisor = Supervisor(store, runner, holder="supervisor-a", now=clock)
    await store.put(desired())
    await supervisor.reconcile_once()
    attempts = len(runner.calls)

    for _ in range(5):
        clock.advance(600)
        assert await supervisor.reconcile_once() == []

    assert len(runner.calls) == attempts, "the supervisor retried a halted account"


async def test_an_operator_clears_a_halt_by_restating_the_desire(
    store: LiveStateStore, clock: Clock
) -> None:
    # Re-stating bumps the revision, which is a deliberate act rather than an
    # automatic one.
    runner = DisagreeingRunner()
    supervisor = Supervisor(store, runner, holder="supervisor-a", now=clock)
    await store.put(desired())
    await supervisor.reconcile_once()

    await store.put(desired())  # the operator says "try again"
    actions = await supervisor.reconcile_once()

    assert [a.action for a in actions] == ["halted"]
    assert len(runner.calls) == 2


async def test_a_halted_account_can_still_be_stopped(
    store: LiveStateStore, clock: Clock
) -> None:
    # Halted must not mean unreachable: stopping is the one thing that should
    # always work. Until Phase 5 acceptance this test asserted the opposite of
    # its own comment -- the account stayed HALTED and the pass did nothing --
    # which left desired STOPPED and observed HALTED never converging.
    runner = DisagreeingRunner()
    supervisor = Supervisor(store, runner, holder="supervisor-a", now=clock)
    await store.put(desired())
    await supervisor.reconcile_once()

    await store.stop("acct_1")
    actions = await supervisor.reconcile_once()

    assert [action.action for action in actions] == ["stop"]
    assert (await store.observed("acct_1")).status is ObservedStatus.STOPPED  # type: ignore[union-attr]
    # And it settles there rather than flapping.
    assert await supervisor.reconcile_once() == []


def test_halted_is_the_only_status_needing_an_operator() -> None:
    from engine.live.desired_state import ObservedStatus as S

    assert [s for s in S if s.needs_operator] == [S.HALTED]


# --- the crash loop, bounded ---------------------------------------------
#
# Every defect found in live so far has been a *startup* failure: a node that
# comes up, does nothing, and exits. Without a backoff the supervisor respawns
# it every pass, forever -- which against a real venue is also how an IP gets
# rate-limited.


async def test_repeated_failures_back_off_exponentially(
    store: LiveStateStore, supervisor: Supervisor, runner: RecordingRunner, clock: Clock
) -> None:
    runner.fail_on_start = True
    await store.put(desired())

    attempts = []
    for _ in range(40):
        actions = await supervisor.reconcile_once()
        attempts.append(bool(actions))
        clock.advance(5)

    # Forty passes over 200 simulated seconds. Without a backoff every one is
    # an attempt; with it the gaps widen: 5s, 10s, 20s, 40s, 80s.
    assert sum(attempts) <= 7, f"{sum(attempts)} attempts is a crash loop"
    assert sum(attempts) >= 4, "it must keep trying, not give up"


async def test_the_delay_is_capped(
    store: LiveStateStore, runner: RecordingRunner, clock: Clock
) -> None:
    """Bounded rather than unbounded doubling.

    An account that starts failing at 03:00 should still be retried at 09:00,
    roughly every five minutes -- not once a day.
    """
    supervisor = Supervisor(
        store,
        runner,
        holder="supervisor-a",
        restart_backoff_seconds=5.0,
        restart_backoff_max_seconds=60.0,
        now=clock,
    )
    runner.fail_on_start = True
    await store.put(desired())
    for _ in range(10):
        await supervisor.reconcile_once()
        clock.advance(120)

    state = supervisor._backoff["acct_1"]  # noqa: SLF001

    assert state.delay_seconds(5.0, 60.0) == 60.0


async def test_a_node_that_runs_long_enough_clears_the_backoff(
    store: LiveStateStore, runner: RecordingRunner, clock: Clock
) -> None:
    """A start is judged after the fact, by how long the node lived.

    Ten seconds of being in the process table is not a successful start; a
    minute of actually running is.
    """
    supervisor = Supervisor(
        store, runner, holder="supervisor-a", healthy_after_seconds=60.0, now=clock
    )
    runner.fail_on_start = True
    await store.put(desired())
    await supervisor.reconcile_once()
    assert supervisor._backoff["acct_1"].failures == 1  # noqa: SLF001

    # It starts, and this time it lives.
    runner.fail_on_start = False
    clock.advance(10)
    await supervisor.reconcile_once()
    clock.advance(120)
    runner.running.discard("acct_1")
    await supervisor.reconcile_once()

    assert supervisor._backoff["acct_1"].failures == 0  # noqa: SLF001


async def test_a_short_lived_node_counts_as_a_failure(
    store: LiveStateStore, runner: RecordingRunner, clock: Clock
) -> None:
    """The exact shape of every live defect so far.

    The process starts, is briefly alive, and exits with status 0. Nothing
    raised, and the supervisor must not read "it started" as "it worked".
    """
    supervisor = Supervisor(
        store, runner, holder="supervisor-a", healthy_after_seconds=60.0, now=clock
    )
    await store.put(desired())
    await supervisor.reconcile_once()

    clock.advance(5)
    runner.running.discard("acct_1")  # it died
    await supervisor.reconcile_once()

    assert supervisor._backoff["acct_1"].failures == 1  # noqa: SLF001


async def test_an_operator_stopping_an_account_clears_its_backoff(
    store: LiveStateStore, supervisor: Supervisor, runner: RecordingRunner, clock: Clock
) -> None:
    # Asking for a stop is not a failed start, and an account restarted later
    # should not inherit a delay from before it was turned off.
    runner.fail_on_start = True
    await store.put(desired())
    await supervisor.reconcile_once()

    await store.stop("acct_1")
    await supervisor.reconcile_once()

    assert "acct_1" not in supervisor._backoff  # noqa: SLF001


async def test_a_healthy_account_is_never_delayed(
    store: LiveStateStore, supervisor: Supervisor, clock: Clock
) -> None:
    # The backoff must be invisible to an account that is simply working.
    await store.put(desired())
    await supervisor.reconcile_once()

    for _ in range(5):
        clock.advance(10)
        await store.heartbeat("acct_1")
        assert await supervisor.reconcile_once() == []


async def test_a_new_spec_does_not_wait_out_a_backoff(
    store: LiveStateStore, supervisor: Supervisor, runner: RecordingRunner, clock: Clock
) -> None:
    """Restating the desired state is an operator saying "try this instead".

    It is a new thing to attempt, not a retry of the failing one -- the same
    gesture that clears a halt.
    """
    runner.fail_on_start = True
    await store.put(desired())
    await supervisor.reconcile_once()
    runner.fail_on_start = False

    await store.put(desired(strategy_version_id="sv_2"))  # revision 2
    actions = await supervisor.reconcile_once()  # no clock advance

    # "start" rather than "restart": the failed account was not running, so
    # there is nothing to stop first. What matters is that it was not deferred.
    assert [a.action for a in actions] == ["start"]
    assert "acct_1" in runner.running


async def test_a_node_that_wedges_after_an_hour_is_not_penalised(
    store: LiveStateStore, runner: RecordingRunner, clock: Clock
) -> None:
    # The stale-heartbeat path is judged like any other start. A node that ran
    # for an hour and then stopped talking has earned an immediate restart.
    supervisor = Supervisor(
        store, runner, holder="supervisor-a", healthy_after_seconds=60.0, now=clock
    )
    await store.put(desired())
    await supervisor.reconcile_once()

    clock.advance(3600)
    actions = await supervisor.reconcile_once()

    assert [a.action for a in actions] == ["restart"]
    assert supervisor._backoff["acct_1"].failures == 0  # noqa: SLF001


# --- one account's problem is not every account's ------------------------


async def test_an_unreadable_record_does_not_stall_the_pass(
    store: LiveStateStore, supervisor: Supervisor, runner: RecordingRunner
) -> None:
    """A record written by an older version, corrupted, or hand-edited.

    Adding one required field to `DesiredState` makes every record written
    before it unparseable -- which is how this was found. Without isolation the
    exception leaves the loop and every *other* account goes untended for as
    long as the bad one exists.
    """
    await store.put(desired("acct_1"))
    await store.put(desired("acct_2"))
    await store._redis.set(  # noqa: SLF001
        "live:desired:acct_1", '{"account_id": "acct_1", "venue": "BINANCE"}'
    )

    actions = await supervisor.reconcile_once()

    assert [a.account_id for a in actions] == ["acct_2"]
    assert "acct_2" in runner.running


async def test_an_unreadable_record_does_not_stop_a_running_node(
    store: LiveStateStore, supervisor: Supervisor, runner: RecordingRunner
) -> None:
    """The node holds the position; the record only describes it.

    Stopping a live node because its description became unreadable would turn a
    bookkeeping problem into a market one.
    """
    await store.put(desired("acct_1"))
    await supervisor.reconcile_once()
    assert "acct_1" in runner.running

    await store._redis.set("live:desired:acct_1", "{ this is not json")  # noqa: SLF001
    await supervisor.reconcile_once()

    assert "acct_1" in runner.running


async def test_the_bad_account_is_named_in_the_logs(
    store: LiveStateStore, supervisor: Supervisor, caplog: pytest.LogCaptureFixture
) -> None:
    # Skipping quietly would leave an account unsupervised with nothing said.
    await store.put(desired("acct_1"))
    await store._redis.set("live:desired:acct_1", "not json at all")  # noqa: SLF001

    with caplog.at_level("ERROR"):
        await supervisor.reconcile_once()

    assert any("could not reconcile" in record.message for record in caplog.records)
