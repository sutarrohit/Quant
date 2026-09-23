"""The control plane's entry point.

Thin by design, so what is tested is the wiring rather than the logic: that the
kill switch is really a composite, that a lease says which process holds an
account, that a shutdown hands the accounts back, and that a missing Redis is
refused at boot instead of discovered by hanging.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import fakeredis
import fakeredis.aioredis
import pytest

from engine.errors import PreflightFailed
from engine.live.desired_state import LiveStateStore
from engine.live.kill_switch import CompositeKillSwitch, FileKillSwitch, RedisKillSwitch
from engine.live.main import Components, build_components, holder_id, preflight, run
from engine.live.supervisor import Supervisor
from engine.settings import Settings
from engine.types.state import ObservedStatus
from tests.live.conftest import Clock, RecordingRunner, desired


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "redis_url": "redis://localhost:6379/0",
        "cache_redis_url": "redis://localhost:6380/0",
        "internal_api_key": "x",
        "log_level": "ERROR",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


# --- wiring --------------------------------------------------------------


def test_the_kill_switch_is_a_composite(tmp_path: Path) -> None:
    """The one mistake in this file that would be silently useless.

    A single-path kill switch still passes every test the switch itself has;
    it just stops working on the day the path it uses is the broken one.
    """
    components = build_components(settings(live_kill_switch_dir=str(tmp_path)))

    switch = components.runner._kill_switch  # noqa: SLF001
    assert isinstance(switch, CompositeKillSwitch)
    kinds = {type(path) for path in switch._switches}  # noqa: SLF001
    assert kinds == {RedisKillSwitch, FileKillSwitch}


def test_the_file_switch_uses_the_configured_directory(tmp_path: Path) -> None:
    components = build_components(settings(live_kill_switch_dir=str(tmp_path / "kill")))

    file_switch = next(
        path
        for path in components.runner._kill_switch._switches  # noqa: SLF001
        if isinstance(path, FileKillSwitch)
    )
    assert file_switch._directory == tmp_path / "kill"  # noqa: SLF001


def test_a_holder_names_the_process(tmp_path: Path) -> None:
    """A bare UUID would say only that *someone* holds the account.

    At 3am, looking at a stranded lease, the host and pid are the difference
    between "restart that box" and a search.
    """
    import os

    holder = holder_id()

    assert holder.endswith(f":{os.getpid()}")
    assert len(holder.split(":")[0]) > 0


def test_the_supervisor_carries_the_holder(tmp_path: Path) -> None:
    components = build_components(settings(), holder="host-a:1")
    assert components.supervisor.holder == "host-a:1"


def test_the_lease_seconds_come_from_settings() -> None:
    components = build_components(settings(live_lease_seconds=11))
    assert components.store._lease_seconds == 11  # noqa: SLF001


# --- preflight -----------------------------------------------------------


async def test_an_unreachable_cache_redis_is_refused_at_boot() -> None:
    """Not defensive tidiness.

    `TradingNode(config)` blocks indefinitely when its cache Redis is
    unreachable and does not die on SIGTERM (D16), so a supervisor that
    discovered this by trying would hang its whole loop for every account. A
    deploy that fails beats a deploy that wedges.
    """
    with pytest.raises(PreflightFailed, match="did not answer"):
        # Port 1 is reserved and refuses immediately.
        await preflight(settings(redis_url="redis://localhost:1/0"))


async def test_a_missing_cache_url_is_refused_at_boot() -> None:
    with pytest.raises(PreflightFailed, match="NT_CACHE_REDIS_URL"):
        await preflight(settings(cache_redis_url=None))


async def test_the_failure_names_which_redis(tmp_path: Path) -> None:
    # Two Redis instances, deliberately -- an operator must not have to guess
    # which one is down.
    with pytest.raises(PreflightFailed) as raised:
        await preflight(settings(redis_url="redis://localhost:1/0"))

    assert raised.value.details is not None
    assert raised.value.details["redis"] == "queue"


# --- shutdown hands the accounts back ------------------------------------


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(clock: Clock) -> LiveStateStore:
    redis = fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    return LiveStateStore(redis, lease_seconds=30, now=clock)


async def test_shutdown_releases_the_lease(
    store: LiveStateStore, clock: Clock
) -> None:
    """A deploy is not a crash and should not be treated as one.

    Without this the next supervisor waits out a heartbeat timeout -- ninety
    seconds with nobody managing a stop -- to learn something this one knew.
    """
    runner = RecordingRunner()
    supervisor = Supervisor(store, runner, holder="host-a:1", now=clock)
    await store.put(desired("acct_1"))
    await supervisor.reconcile_once()
    assert await store.lease_holder("acct_1") == "host-a:1"

    await supervisor.shutdown()

    assert await store.lease_holder("acct_1") is None
    assert "acct_1" not in runner.running


async def test_shutdown_records_that_nothing_is_running(
    store: LiveStateStore, clock: Clock
) -> None:
    # STOPPED is simply true once the node is gone, and a status that is not
    # live is reason enough for the next supervisor to start -- so recovery
    # does not have to wait for the heartbeat to go stale.
    supervisor = Supervisor(store, RecordingRunner(), holder="host-a:1", now=clock)
    await store.put(desired("acct_1"))
    await supervisor.reconcile_once()

    await supervisor.shutdown()

    observed = await store.observed("acct_1")
    assert observed is not None
    assert observed.status is ObservedStatus.STOPPED


async def test_the_next_supervisor_picks_it_up_immediately(
    store: LiveStateStore, clock: Clock
) -> None:
    first = Supervisor(store, RecordingRunner(), holder="host-a:1", now=clock)
    await store.put(desired("acct_1"))
    await first.reconcile_once()
    await first.shutdown()

    second_runner = RecordingRunner()
    second = Supervisor(store, second_runner, holder="host-b:2", now=clock)
    actions = await second.reconcile_once()  # no clock advance at all

    assert [action.action for action in actions] == ["start"]
    assert "acct_1" in second_runner.running


async def test_shutdown_only_hands_back_what_it_held(
    store: LiveStateStore, clock: Clock
) -> None:
    # Another supervisor's account must not have its lease released by this
    # one's shutdown; that would put two nodes on one account.
    supervisor = Supervisor(store, RecordingRunner(), holder="host-a:1", now=clock)
    await store.put(desired("acct_1"))
    await store.acquire("acct_2", "host-b:2")

    await supervisor.shutdown()

    assert await store.lease_holder("acct_2") == "host-b:2"


async def test_a_node_that_will_not_stop_does_not_strand_the_others(
    store: LiveStateStore, clock: Clock
) -> None:
    class Stubborn(RecordingRunner):
        async def stop(self, account_id: str) -> None:
            if account_id == "acct_1":
                raise RuntimeError("the socket is wedged")
            await RecordingRunner.stop(self, account_id)

    supervisor = Supervisor(store, Stubborn(), holder="host-a:1", now=clock)
    await store.put(desired("acct_1"))
    await store.put(desired("acct_2"))
    await supervisor.reconcile_once()

    await supervisor.shutdown()

    assert await store.lease_holder("acct_1") is None
    assert await store.lease_holder("acct_2") is None


async def test_shutdown_is_idempotent(store: LiveStateStore, clock: Clock) -> None:
    supervisor = Supervisor(store, RecordingRunner(), holder="host-a:1", now=clock)
    await store.put(desired("acct_1"))
    await supervisor.reconcile_once()

    await supervisor.shutdown()
    await supervisor.shutdown()

    assert await store.lease_holder("acct_1") is None


# --- the loop ------------------------------------------------------------


async def test_cancelling_the_loop_runs_the_shutdown(
    store: LiveStateStore, clock: Clock
) -> None:
    """What a SIGTERM does, one layer down.

    `main` cancels the task; everything that matters happens in `run`'s
    `finally`, and this is that path.
    """
    runner = RecordingRunner()
    supervisor = Supervisor(store, runner, holder="host-a:1", now=clock)
    components = Components(
        settings(),
        fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True),
        store,
        runner,  # type: ignore[arg-type]
        supervisor,
    )
    await store.put(desired("acct_1"))

    task = asyncio.create_task(run(components, interval_seconds=0.01))
    await asyncio.sleep(0.05)
    assert "acct_1" in runner.running
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert "acct_1" not in runner.running
    assert await store.lease_holder("acct_1") is None
