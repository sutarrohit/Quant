"""Building a live node's config.

The config builder is pure, so every safety property here is tested without a
network, a key, or a running exchange — which is the point, because these are
the properties that matter when one of those is missing.
"""

from __future__ import annotations

import asyncio

import pytest

from engine.errors import CacheNotIsolated, LiveNotPermitted
from engine.live.credentials import EnvironmentCredentialResolver
from engine.live.desired_state import TradingMode
from engine.live.kill_switch import NeverEngaged
from engine.live.node import assert_cache_is_isolated, build_cache_config, build_node_config
from engine.settings import Settings
from engine.strategies.config import CONFIG_PATH, STRATEGY_PATH, strategy_config
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


# --- live is gated -------------------------------------------------------


def test_live_mode_refuses_to_build() -> None:
    """ADR-001 records seven conditions before a real key is loaded.

    None are met. A node that quietly traded because the code happened to work
    is exactly what that ADR exists to prevent.
    """
    with pytest.raises(LiveNotPermitted, match="adr-001"):
        build_node_config(desired(mode=TradingMode.LIVE, credential_ref="ref"), settings())


def test_simulation_mode_builds() -> None:
    assert build_node_config(desired(mode=TradingMode.SIMULATION), settings()) is not None


def test_a_simulation_node_holds_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulation risks nothing and needs nothing; it must not be gated on a key.
    monkeypatch.delenv("NT_VENUE_ANY_KEY", raising=False)
    config = build_node_config(
        desired(mode=TradingMode.SIMULATION),
        settings(),
        resolver=EnvironmentCredentialResolver(),
    )
    assert "***" not in str(config)


# --- the cache must be isolated from the queue ---------------------------


def test_a_shared_redis_instance_is_refused() -> None:
    """Spec section 9.2.

    A FLUSHDB aimed at the job queue must never be able to erase live position
    state. Nautilus's DatabaseConfig exposes only host and port, with no way to
    select a logical database (D15), so instance is the only separation
    available — and it has to be checked rather than assumed.
    """
    with pytest.raises(CacheNotIsolated, match="same Redis instance"):
        assert_cache_is_isolated("redis://localhost:6379/1", "redis://localhost:6379/0")


def test_a_different_port_is_accepted() -> None:
    assert_cache_is_isolated("redis://localhost:6380/0", "redis://localhost:6379/0")


def test_a_different_host_is_accepted() -> None:
    assert_cache_is_isolated("redis://cache:6379/0", "redis://queue:6379/0")


def test_a_different_logical_db_is_not_enough() -> None:
    # It would satisfy the spec's wording, and Nautilus cannot honour it: the
    # DB index in the URL never reaches DatabaseConfig, so both would land on
    # database 0 of one instance.
    with pytest.raises(CacheNotIsolated):
        assert_cache_is_isolated("redis://localhost:6379/5", "redis://localhost:6379/0")


def test_live_requires_a_cache_url() -> None:
    # Without it a restart loses every open order and position, and recovery
    # has nothing to compare the venue against.
    with pytest.raises(CacheNotIsolated, match="NT_CACHE_REDIS_URL"):
        build_cache_config(settings(cache_redis_url=None))


def test_flush_on_start_is_never_true() -> None:
    # It wipes exactly the state recovery depends on (spec section 9.2).
    assert build_cache_config(settings()).flush_on_start is False


def test_the_node_config_carries_the_cache() -> None:
    config = build_node_config(desired(), settings())
    assert config.cache is not None
    assert config.cache.database is not None
    assert config.cache.flush_on_start is False


# --- the shared strategy config ------------------------------------------


def test_the_strategy_config_comes_from_the_shared_factory() -> None:
    """Spec section 10.2, the platform's core guarantee.

    A live node's strategy config must be identical in shape to a backtest's.
    If this module ever constructs it inline, this fails — which is the point.
    """
    state = desired()
    expected = strategy_config(
        instrument_id=state.instrument_id,
        bar_type=state.bar_type,
        spec=state.spec,
        strategy_version_id=state.strategy_version_id,
        spec_hash=state.spec_hash,
        # Declared by the operator: the venue cannot supply it (D20). Taker
        # plus slippage, the same sum a backtest uses, so the two size alike.
        cost_bps=str(state.fees.cost_bps),
    )
    assert build_node_config(state, settings()).strategies[0] == expected


def test_the_strategy_paths_match_the_backtest() -> None:
    strategy = build_node_config(desired(), settings()).strategies[0]
    assert strategy.strategy_path == STRATEGY_PATH
    assert strategy.config_path == CONFIG_PATH


def test_the_spec_hash_travels_to_the_node() -> None:
    state = desired(spec_hash="deadbeef")
    assert build_node_config(state, settings()).strategies[0].config["spec_hash"] == "deadbeef"


# --- one node per account ------------------------------------------------


def test_each_account_gets_its_own_trader_id() -> None:
    # An account is the unit of risk, credentials and reconciliation, so it is
    # the unit of process isolation (spec section 10.1).
    first = build_node_config(desired("acct_1"), settings()).trader_id
    second = build_node_config(desired("acct_2"), settings()).trader_id
    assert first != second


def test_a_trader_id_survives_an_awkward_account_id() -> None:
    config = build_node_config(desired("acct/1-with.punctuation"), settings())
    assert str(config.trader_id).startswith("NT-")


# --- purity --------------------------------------------------------------


def test_building_is_deterministic() -> None:
    state = desired()
    first = build_node_config(state, settings())
    second = build_node_config(state, settings())
    assert first.strategies[0] == second.strategies[0]
    assert first.trader_id == second.trader_id


# --- reconciliation gates the start --------------------------------------


async def test_simulation_skips_reconciliation(tmp_path: object) -> None:
    """Simulation has no venue state to disagree with — the fills were imagined.

    It skips loudly rather than silently, and must not be gated on readers it
    has no use for.
    """
    import fakeredis
    import fakeredis.aioredis

    from engine.live.desired_state import LiveStateStore
    from engine.live.node import LiveNodeRunner

    store = LiveStateStore(
        fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    )
    runner = LiveNodeRunner(settings(), store, kill_switch=NeverEngaged())

    # No cache or venue reader supplied, and simulation must still be startable.
    await runner._reconcile(desired(mode=TradingMode.SIMULATION))  # noqa: SLF001


async def test_live_without_readers_refuses_to_reconcile() -> None:
    """Live cannot skip. A node that starts on unverified state is worse than
    one that stays down (spec section 10.3)."""
    import fakeredis
    import fakeredis.aioredis

    from engine.live.desired_state import LiveStateStore
    from engine.live.node import LiveNodeRunner
    from engine.live.recovery import ReconciliationFailed

    store = LiveStateStore(
        fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    )
    runner = LiveNodeRunner(settings(), store, kill_switch=NeverEngaged())

    with pytest.raises(ReconciliationFailed, match="reconcile against"):
        await runner._reconcile(  # noqa: SLF001
            desired(mode=TradingMode.LIVE, credential_ref="ref")
        )


async def test_live_reconciles_before_starting() -> None:
    # The order is the spec's: cache, venue, compare, and only then start.
    from decimal import Decimal

    import fakeredis
    import fakeredis.aioredis

    from engine.live.desired_state import LiveStateStore
    from engine.live.node import LiveNodeRunner
    from engine.live.recovery import (
        AccountSnapshot,
        PositionSnapshot,
        ReconciliationFailed,
    )

    class Reader:
        def __init__(self, state: AccountSnapshot) -> None:
            self._state = state

        async def snapshot(self, account_id: str) -> AccountSnapshot:
            return self._state

    store = LiveStateStore(
        fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    )
    runner = LiveNodeRunner(
        settings(),
        store,
        kill_switch=NeverEngaged(),
        cache_reader=Reader(AccountSnapshot()),
        venue_reader=Reader(
            AccountSnapshot(
                positions=(PositionSnapshot("BTCUSDT.BINANCE", Decimal("0.5"), "LONG"),)
            )
        ),
    )

    with pytest.raises(ReconciliationFailed, match="POSITION_ONLY_AT_VENUE"):
        await runner._reconcile(  # noqa: SLF001
            desired(mode=TradingMode.LIVE, credential_ref="ref")
        )


# --- one process per account ---------------------------------------------
#
# The parent's half. `tests/live/test_worker.py` covers what the child does.


def runner(**overrides: object) -> object:
    import fakeredis
    import fakeredis.aioredis

    from engine.live.desired_state import LiveStateStore
    from engine.live.node import LiveNodeRunner

    store = LiveStateStore(
        fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    )
    return LiveNodeRunner(settings(), store, kill_switch=NeverEngaged(), **overrides)  # type: ignore[arg-type]


def sleeper(seconds: float = 30.0) -> None:  # pragma: no cover - runs in a child
    import time

    time.sleep(seconds)


def exits_immediately() -> None:  # pragma: no cover - runs in a child
    """A child that is simply gone by the time the parent looks."""


def deaf(seconds: float = 30.0) -> None:  # pragma: no cover - runs in a child
    """A child that ignores SIGTERM, which is what the kill path is for."""
    import signal
    import time

    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(seconds)


async def spawn(run: object, target: object = sleeper) -> None:
    """Start a stand-in child instead of a real node.

    A real one needs a Redis and several seconds of `nautilus_trader` import.
    What is under test here is the process lifecycle, so the child only has to
    exist and be killable.
    """
    from engine.live.node import _CONTEXT

    process = _CONTEXT.Process(target=target, daemon=False)
    process.start()
    run._processes["acct_1"] = process  # noqa: SLF001


async def test_a_started_account_has_its_own_process() -> None:
    """The isolation the spec asked for from the beginning (section 10.1).

    Every account in one process meant every account shared every fatal fault
    -- and made `dispose()` close the supervisor's own event loop (D18).
    """
    run = runner()
    await spawn(run)
    try:
        assert await run.is_running("acct_1")
        assert run._processes["acct_1"].pid != __import__("os").getpid()  # noqa: SLF001
    finally:
        await run.stop("acct_1")


async def test_stopping_terminates_the_process() -> None:
    run = runner()
    await spawn(run)

    await run.stop("acct_1")

    assert not await run.is_running("acct_1")


async def test_a_child_that_ignores_sigterm_is_killed() -> None:
    """An account that cannot be stopped is worse than one stopped abruptly.

    The grace period exists so a healthy child can stop its node and dispose
    it. A child that will not take SIGTERM does not get to hold the account.
    """
    run = runner(stop_grace_seconds=0.5)
    await spawn(run, target=deaf)

    await run.stop("acct_1")

    assert not await run.is_running("acct_1")


async def test_a_child_that_exits_on_its_own_is_noticed() -> None:
    """Liveness is the operating system's answer, not an inference.

    The supervisor still has the heartbeat for the case that matters more --
    a process that is alive and wedged -- but a process that is simply gone is
    seen on the next pass rather than after a 90-second timeout.
    """
    run = runner()
    await spawn(run, target=exits_immediately)
    await asyncio.sleep(0.3)

    assert not await run.is_running("acct_1")
    # And it is reaped rather than left in the map to be asked about forever.
    assert "acct_1" not in run._processes  # noqa: SLF001


async def test_stopping_something_that_was_never_started_is_quiet() -> None:
    await runner().stop("never_seen")


async def test_stop_all_stops_every_child() -> None:
    # What the control plane's own shutdown calls. A live node outliving its
    # supervisor is the one outcome worth being thorough about.
    run = runner()
    await spawn(run)

    await run.stop_all()

    assert run._processes == {}  # noqa: SLF001


async def test_the_parent_holds_no_nautilus_object() -> None:
    """What crosses the boundary is JSON.

    The parent importing and holding a `TradingNode` is how the shared-loop
    defect happened; the attribute not existing is what keeps it fixed.
    """
    run = runner()

    assert not hasattr(run, "_nodes")
    assert not hasattr(run, "_gates")
