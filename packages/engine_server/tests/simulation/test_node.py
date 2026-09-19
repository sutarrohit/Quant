"""Assembling a sandbox node.

Three defects lived here until this file and `test_boot.py` existed, and all
three survived every other test because nothing ever built a node:

* the node declared `Environment.LIVE` while running a simulated exchange;
* no client factory was registered, and `TradingNodeBuilder` logs that at ERROR
  and then *continues* -- so the node built, started, heartbeated and traded
  nothing, looking healthy the whole time;
* the pure fix for the second does not work. Nautilus special-cases the sandbox
  factory with `factory.__name__`, which only a class has, and the
  `ImportableConfig` route hands it an instance.

So the wiring is imperative, and these tests are shaped around the one property
that matters: a node cannot come up without the factories its clients need.
"""

from __future__ import annotations

from typing import Any

import pytest
from nautilus_trader.common import Environment
from nautilus_trader.live.factories import LiveDataClientFactory, LiveExecClientFactory

from engine.errors import LiveNotPermitted, VenueNotSupported
from engine.live.desired_state import TradingMode
from engine.live.node import build_node_config
from engine.settings import Settings
from engine.simulation.node import (
    clients,
    data_client,
    data_factory,
    exec_factory,
    execution_client,
    register_factories,
)
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


class FakeNode:
    """Records what was registered, which is all `register_factories` does."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.execution: dict[str, Any] = {}

    def add_data_client_factory(self, name: str, factory: type) -> None:
        self.data[name] = factory

    def add_exec_client_factory(self, name: str, factory: type) -> None:
        self.execution[name] = factory


# --- the environment -----------------------------------------------------


def test_the_environment_is_sandbox_not_live() -> None:
    """Nautilus defaults `environment` to LIVE, and we did not override it.

    A node running a simulated exchange while declaring itself live is asking
    for reconciliation and connection behaviour to disagree with what is
    actually happening.
    """
    config = build_node_config(desired(mode=TradingMode.SIMULATION), settings())

    assert config.environment is Environment.SANDBOX


def test_live_mode_still_refuses_to_build() -> None:
    # Renaming PAPER to SIMULATION must not have opened the gate.
    with pytest.raises(LiveNotPermitted, match="adr-001"):
        build_node_config(desired(mode=TradingMode.LIVE, credential_ref="ref"), settings())


# --- factories are registered, and are classes ---------------------------


def test_both_factories_are_registered() -> None:
    """The defect this file exists for.

    Without them the builder logs an error and continues, and the node comes up
    with no clients at all -- silently inert, which survives a smoke test in a
    way a crash would not.
    """
    node = FakeNode()

    register_factories(node, desired(venue="BINANCE"))

    assert set(node.data) == {"BINANCE"}
    assert set(node.execution) == {"BINANCE"}


def test_the_factories_are_classes_not_instances() -> None:
    """Nautilus checks `factory.__name__` to special-case the sandbox client.

    Only a class has one. Passing an instance -- which is what carrying the
    factory in an `ImportableConfig` does -- kills the build with
    `AttributeError` (D17).
    """
    node = FakeNode()
    register_factories(node, desired())

    for factory in list(node.data.values()) + list(node.execution.values()):
        assert isinstance(factory, type), factory
        assert hasattr(factory, "__name__")


def test_the_factories_are_the_right_kind() -> None:
    assert issubclass(data_factory("BINANCE"), LiveDataClientFactory)
    assert issubclass(exec_factory("BINANCE"), LiveExecClientFactory)


def test_the_sandbox_factory_keeps_the_name_nautilus_looks_for() -> None:
    # A rename upstream would silently drop the portfolio kwarg the sandbox
    # client needs, so the coupling is asserted rather than hoped for.
    assert exec_factory("BINANCE").__name__ == "SandboxLiveExecClientFactory"


def test_an_unknown_venue_raises() -> None:
    """Raised, not logged.

    Nautilus's own behaviour is to log at ERROR and carry on, which produces a
    node that trades nothing and reports itself healthy.
    """
    with pytest.raises(VenueNotSupported, match="KRAKEN"):
        data_factory("KRAKEN")

    with pytest.raises(VenueNotSupported):
        exec_factory("KRAKEN")


def test_registering_an_unknown_venue_raises_before_anything_is_set() -> None:
    node = FakeNode()

    with pytest.raises(VenueNotSupported):
        register_factories(node, desired(venue="KRAKEN"))

    assert node.data == {}
    assert node.execution == {}


# --- the clients ---------------------------------------------------------


def test_clients_are_keyed_by_the_accounts_venue() -> None:
    # The builder splits the key on "-" and looks the factory up by that name,
    # so a mismatch here is another silent no-client node.
    data, execution = clients(desired(venue="BINANCE"))

    assert set(data) == {"BINANCE"}
    assert set(execution) == {"BINANCE"}


def test_every_client_in_the_config_has_a_factory() -> None:
    # Stated over the whole config rather than per client, so a third client
    # added later is covered by a test nobody had to remember to write.
    config = build_node_config(desired(), settings())
    node = FakeNode()
    register_factories(node, desired())

    assert set(config.data_clients) <= set(node.data)
    assert set(config.exec_clients) <= set(node.execution)


def test_a_simulated_account_starts_with_a_balance() -> None:
    assert execution_client(desired()).starting_balances


def test_fills_come_from_bars() -> None:
    """The strategy trades bars, so the simulator must fill on them.

    Without `bar_execution` a bar-driven strategy submits orders that nothing
    ever matches, and the run looks like a strategy that found no signals.
    """
    assert execution_client(desired()).bar_execution is True


def test_the_data_client_needs_no_credentials() -> None:
    # Public streams. A simulation node holds no key.
    built = data_client(desired())
    assert built.api_key is None
    assert built.api_secret is None


# --- purity --------------------------------------------------------------


def test_building_is_deterministic() -> None:
    state = desired()
    assert build_node_config(state, settings()).data_clients == (
        build_node_config(state, settings()).data_clients
    )
