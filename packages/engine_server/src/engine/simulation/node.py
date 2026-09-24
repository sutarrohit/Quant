"""Assembling a sandbox node: live data in, simulated fills out.

Nautilus has three environments -- `backtest`, `sandbox` and `live` -- and this
builds the middle one. A real Binance feed drives a simulated matching engine,
so the strategy sees exactly what it would see in production and no money moves.

**Three defects were found here by writing this module and a test that actually
builds a node** (docs/nautilus-api-notes.md D17). All three had survived every
other test, because until now nothing ever built one:

1. The environment was left at Nautilus's default, `LIVE`, while the execution
   client was a sandbox one.
2. No client factory was registered. `TradingNodeBuilder` logs that at ERROR
   and then **continues**, so the node built, started, heartbeated and looked
   healthy with no data client and no execution client at all. Silently inert
   is a worse failure than a crash, and it is the one that survives a smoke
   test.
3. The obvious fix for (2) does not work. Carrying the factory inside an
   `ImportableConfig` would make the wiring pure data, and the builder does
   resolve it -- but it stores `cfg.factory.create()`, an *instance*, and then
   special-cases the sandbox client with `factory.__name__ == "Sandbox..."`,
   which only a class has. The node dies with `AttributeError` on build.

So registration is imperative: `add_*_client_factory` takes the class, which is
what the `__name__` check needs. That splits node assembly into a pure config
and a small registration step, and `register_factories` exists to make the
second impossible to forget -- it is called from one place, and an unknown
venue **raises** rather than being logged past.
"""

from __future__ import annotations

from typing import Any

from engine.errors import VenueNotSupported
from engine.types.state import DesiredState

#: What a simulated account starts with. Fixed rather than configurable: a
#: simulation's balance is not a number anyone should be tuning to make a
#: result look better.
STARTING_BALANCES = ["10_000 USDT"]


def data_factory(venue: str) -> type:
    """The class -- not an instance. `add_data_client_factory` wants a type."""
    from nautilus_trader.adapters.binance import BinanceLiveDataClientFactory

    factories: dict[str, type] = {"BINANCE": BinanceLiveDataClientFactory}
    if venue not in factories:
        raise VenueNotSupported(
            f"no live data adapter for venue {venue}",
            details={"venue": venue, "supported": sorted(factories)},
        )
    return factories[venue]


def exec_factory(venue: str) -> type:
    """The sandbox factory, for every venue.

    Simulation fills are simulated wherever the data comes from, so the venue
    selects the *data* adapter and never the execution one. When live opens,
    this is the function that starts differing by venue.
    """
    from nautilus_trader.adapters.sandbox.factory import SandboxLiveExecClientFactory

    data_factory(venue)  # a venue we cannot get data for is not simulatable
    return SandboxLiveExecClientFactory


def instruments(state: DesiredState) -> Any:
    """Load exactly the instrument this account trades, and nothing else.

    **A live node's cache starts empty.** A backtest is handed its instruments
    from the catalog; a live or sandbox node has to fetch them from the venue,
    and without this the cache has none -- so `DslStrategy.on_start` raises,
    which halts the node's start and exits the process with status 0, looking
    for all the world like a clean shutdown (D19).

    `load_ids` rather than `load_all`: Binance lists thousands of instruments,
    and fetching every one of them to trade a single pair costs startup time
    and memory for no benefit.
    """
    from nautilus_trader.config import InstrumentProviderConfig

    return InstrumentProviderConfig(load_ids=frozenset([state.instrument_id]))


def data_client(state: DesiredState) -> Any:
    """Live market data for one venue.

    Public streams, so no credentials -- a simulation node holds no key, and
    the code path that would resolve one is never reached.
    """
    from nautilus_trader.adapters.binance import BinanceDataClientConfig
    from nautilus_trader.model.identifiers import Venue

    # A `Venue`, not the string it looks like it takes. The config is a msgspec
    # Struct, which does not validate or coerce what is passed positionally, so
    # a string is accepted here and fails much later inside a Cython
    # constructor at node-build time (D17).
    return BinanceDataClientConfig(
        venue=Venue(state.venue),
        instrument_provider=instruments(state),
    )


def execution_client(state: DesiredState) -> Any:
    """A simulated exchange fed by the live feed.

    Simulation is live in every respect except the money: same node, same
    strategy, same feed, same clock. Only the fill is imagined -- and
    optimistically, since it assumes the whole order filled immediately at that
    price. A simulation says the plumbing works; it does not say the fills will
    match.
    """
    from nautilus_trader.adapters.sandbox.config import SandboxExecutionClientConfig

    return SandboxExecutionClientConfig(
        venue=state.venue,
        starting_balances=STARTING_BALANCES,
        account_type="CASH",
        # The simulated matching engine needs the instrument as much as the
        # strategy does -- it prices and sizes fills with it.
        instrument_provider=instruments(state),
        # The strategy trades bars, so the simulator must fill on them. Without
        # this a bar-driven strategy submits orders nothing ever matches, and
        # the run looks like a strategy that found no signals.
        bar_execution=True,
    )


def clients(state: DesiredState) -> tuple[dict[str, Any], dict[str, Any]]:
    """`(data_clients, exec_clients)` keyed by venue, as the node config wants."""
    return {state.venue: data_client(state)}, {state.venue: execution_client(state)}


def register_factories(node: Any, state: DesiredState) -> None:
    """Give the node the factories its clients need, before `build()`.

    Must be called between constructing a `TradingNode` and building it. It is
    called from exactly one place, `LiveNodeRunner.start`, because a second
    caller is a second place to forget it -- and forgetting it does not raise.
    """
    node.add_data_client_factory(state.venue, data_factory(state.venue))
    node.add_exec_client_factory(state.venue, exec_factory(state.venue))


#: Above the strategy's default of 0, so the exchange prices a bar before the
#: strategy acts on it -- the order a backtest uses.
BAR_PRIORITY = 10


def route_bars_to_exchange(node: Any, state: DesiredState) -> None:
    """Feed the account's bars to the simulated exchange. Call after `build()`.

    The sandbox client listens on ``data.*.{venue}.*``, which matches quote and
    trade topics but not ``data.bars.{bar_type}``. The strategy trades bars and
    subscribes to nothing else, so the exchange never had a price and rejected
    every order with "no market" -- `bar_execution=True` alone does nothing.
    """
    from nautilus_trader.model.identifiers import ClientId

    client = node.kernel.exec_engine._clients[ClientId(state.venue)]
    node.kernel.msgbus.subscribe(
        topic=f"data.bars.{state.bar_type}",
        handler=client.on_data,
        priority=BAR_PRIORITY,
    )
