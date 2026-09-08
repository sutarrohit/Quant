"""Actually building a node.

Everything else in this repo asserts on configuration. This asserts on a
`TradingNode` that has been constructed and built, because that is the step
where two defects hid: `TradingNodeBuilder` logs a missing client factory at
ERROR and then **continues**, so a node with no data client and no execution
client builds successfully and looks healthy.

**It needs a real Redis.** Nautilus's cache is not stubbable, and
`TradingNode.__init__` blocks forever without it (D16). So this skips when
there is none, and the pure tests in `test_node.py` are what run everywhere.
A skipped test catches nothing; these two files are deliberately a pair.

    docker run -d -p 6380:6379 redis:7-alpine
    NT_TEST_CACHE_REDIS_URL=redis://localhost:6380/0 uv run pytest tests/simulation
"""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import pytest
import pytest_asyncio

from engine.live.desired_state import TradingMode
from engine.live.node import build_node_config
from engine.settings import Settings
from tests.live.conftest import desired

#: A Redis this test may write to. Defaults to the second instance a live
#: deployment already needs, so a developer who can run the control plane can
#: run this without extra setup.
CACHE_URL = os.environ.get("NT_TEST_CACHE_REDIS_URL", "redis://localhost:6380/0")


def reachable(url: str) -> bool:
    parts = urlparse(url)
    try:
        with socket.create_connection((parts.hostname or "localhost", parts.port or 6379), 1.0):
            return True
    except OSError:
        return False


def venue_reachable() -> bool:
    """A live node fetches its instrument from the venue before it can start."""
    try:
        with socket.create_connection(("api.binance.com", 443), 2.0):
            return True
    except OSError:
        return False


requires_venue = pytest.mark.skipif(
    not venue_reachable(),
    reason="needs network access to api.binance.com to load the instrument",
)

requires_redis = pytest.mark.skipif(
    not reachable(CACHE_URL),
    reason=f"needs a Redis at {CACHE_URL}; run `docker run -d -p 6380:6379 redis:7-alpine`",
)


def settings() -> Settings:
    # The queue URL only has to differ by instance from the cache one --
    # `assert_cache_is_isolated` compares host and port, and refuses a shared
    # instance (D15).
    parts = urlparse(CACHE_URL)
    other_port = 6379 if (parts.port or 6379) != 6379 else 6380
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        redis_url=f"redis://{parts.hostname or 'localhost'}:{other_port}/0",
        cache_redis_url=CACHE_URL,
        internal_api_key="x",
        log_level="ERROR",
    )


@pytest_asyncio.fixture
async def node() -> AsyncIterator[object]:
    """A built node.

    Async because `TradingNode.__init__` calls `asyncio.get_event_loop()` and
    fails without a current one -- which is also true in production, where
    `LiveNodeRunner.start` is a coroutine. A synchronous test passes alone
    (pytest-asyncio leaves a loop behind) and fails in the full suite.

    A Nautilus node holds connections and a lot of memory; one that is not
    disposed leaks both, and a test suite that leaks them OOMs.
    """
    from nautilus_trader.live.node import TradingNode

    from engine.simulation.node import register_factories

    state = desired("boot_test", mode=TradingMode.SIMULATION)
    built = TradingNode(config=build_node_config(state, settings()))
    # Not disposed, deliberately: `dispose()` closes the event loop it was
    # given, which here is pytest-asyncio's (D18). These nodes are built and
    # never run, so there is little to release beyond the reference.
    register_factories(built, state)
    built.build()
    yield built


@requires_redis
async def test_a_simulation_node_builds(node: object) -> None:
    # The smoke test that was missing. Until this ran, `LiveNodeRunner.start()`
    # was code nothing had ever executed.
    assert node.trader is not None  # type: ignore[attr-defined]


@requires_redis
async def test_the_strategy_is_on_the_node(node: object) -> None:
    strategies = node.trader.strategies()  # type: ignore[attr-defined]

    assert len(strategies) == 1
    assert type(strategies[0]).__name__ == "DslStrategy"


@requires_redis
async def test_the_data_client_is_registered(node: object) -> None:
    """The defect, asserted where it actually showed.

    A missing factory does not raise -- the builder logs and continues -- so
    the only way to see it is to ask the built node what clients it has.
    """
    clients = node.kernel.data_engine.registered_clients  # type: ignore[attr-defined]

    assert [str(client) for client in clients] == ["BINANCE"]


@requires_redis
async def test_the_execution_client_is_registered(node: object) -> None:
    clients = node.kernel.exec_engine.registered_clients  # type: ignore[attr-defined]

    assert [str(client) for client in clients] == ["BINANCE"]


@requires_redis
async def test_the_node_is_not_running_yet(node: object) -> None:
    # `build()` assembles; `run()` connects. A build that started trading would
    # make the supervisor's start/stop decisions meaningless.
    assert not node.trader.is_running  # type: ignore[attr-defined]


@requires_redis
async def test_without_its_factories_a_node_builds_and_trades_nothing() -> None:
    """The defect, reproduced deliberately.

    This is what the code did before `register_factories` existed: `build()`
    succeeds, the node reports itself fine, and it has no data client and no
    execution client. Nautilus logs two ERROR lines and continues.

    Kept as a test because it is the reason registration is imperative and
    called from exactly one place -- forgetting it does not raise, and a node
    that silently trades nothing is indistinguishable from a strategy that
    found no signals.
    """
    from nautilus_trader.live.node import TradingNode

    state = desired("boot_unregistered", mode=TradingMode.SIMULATION)
    node = TradingNode(config=build_node_config(state, settings()))
    node.build()  # no exception

    assert node.kernel.data_engine.registered_clients == []
    assert node.kernel.exec_engine.registered_clients == []


def test_the_real_start_path_registers_them() -> None:
    """The property that matters: the code that builds a node does not forget.

    Asserted against `worker.run_account` -- where the node is now built, one
    process per account -- so a refactor that drops the call fails here rather
    than in production, where it does not raise at all.

    No Redis needed: this reads the source, and it should run everywhere.
    """
    import inspect

    from engine.live import worker

    source = inspect.getsource(worker.run_account)

    assert "register_factories" in source
    assert source.index("register_factories") < source.index("node.build()")


@pytest.mark.slow
@requires_redis
@requires_venue
async def test_a_real_child_comes_up_and_stays_up() -> None:
    """The whole path, across the process boundary, for real.

    A child that crashes on a bad config, a missing factory or an import error
    exits within a second or two. So the assertion is that it is *still alive*
    after long enough to have imported `nautilus_trader`, connected to Redis,
    built a node and started running it -- which is the only evidence available
    without a venue, and is exactly what a start that silently failed would
    lack.

    Slow by nature: spawn means a fresh interpreter and a fresh Nautilus
    import. That cost is the price of isolation and is paid once per account
    start, which is not on any hot path.
    """
    import asyncio

    import fakeredis
    import fakeredis.aioredis

    from engine.live.desired_state import LiveStateStore
    from engine.live.kill_switch import NeverEngaged
    from engine.live.node import LiveNodeRunner

    store = LiveStateStore(
        fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    )
    run = LiveNodeRunner(settings(), store, kill_switch=NeverEngaged())
    state = desired("child_up", mode=TradingMode.SIMULATION)

    await run.start(state)
    try:
        # Long enough to import nautilus_trader, fetch the instrument from the
        # venue, connect, and start the strategy. A child that fails any of
        # those is gone well inside this.
        await asyncio.sleep(8)
        process = run._processes["child_up"]  # noqa: SLF001

        assert await run.is_running("child_up"), (
            f"the child exited with code {process.exitcode}; it did not get as far as running"
        )
    finally:
        await run.stop("child_up")

    assert not await run.is_running("child_up")
    # And the parent is untouched -- the D18 regression. When every account
    # shared one process, stopping one closed the supervisor's own loop.
    assert not asyncio.get_running_loop().is_closed()


@pytest.mark.slow
@requires_redis
@requires_venue
async def test_a_stopped_child_exits_rather_than_lingering() -> None:
    """SIGTERM, handled. The child stops its node and disposes it.

    Disposing is safe there and only there: the loop it closes belongs to that
    process alone (D18). A child that lingered would hold the account's lease
    and its cache connection.
    """
    import fakeredis
    import fakeredis.aioredis

    from engine.live.desired_state import LiveStateStore
    from engine.live.kill_switch import NeverEngaged
    from engine.live.node import LiveNodeRunner

    store = LiveStateStore(
        fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    )
    run = LiveNodeRunner(settings(), store, kill_switch=NeverEngaged())
    await run.start(desired("child_stop", mode=TradingMode.SIMULATION))
    process = run._processes["child_stop"]  # noqa: SLF001

    await run.stop("child_stop")

    assert not process.is_alive()
    assert process.exitcode is not None
