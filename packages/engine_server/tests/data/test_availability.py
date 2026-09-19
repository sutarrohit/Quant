"""What the validator may treat as a knowable instrument (ADR-003).

Before automatic provisioning, "knowable" meant "already in the catalog", and a
cold catalog rejected every valid symbol. These tests pin the three answers that
replaced it: held, listed at the venue, and neither.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import fakeredis.aioredis
import httpx
import pytest
import respx
from nautilus_trader.model import Bar

from engine.data.availability import SymbolAvailability
from engine.data.catalog import Catalog
from engine.settings import Settings
from tests.conftest import make_settings
from tests.data.test_binance import EXCHANGE_INFO, EXCHANGE_INFO_BODY

BTC = "BTCUSDT.BINANCE"
SOL = "SOLUSDT.BINANCE"

INVALID_SYMBOL = httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(catalog_path=str(tmp_path / "catalog"), log_level="ERROR")


@pytest.fixture
def catalog_with_btc(settings: Settings, make_bars: Callable[..., list[Bar]]) -> None:
    """A catalog that already holds BTCUSDT bars."""
    Catalog.from_settings(settings).write_bars(make_bars(4))


@pytest.fixture
def redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


def availability(settings: Settings, redis: object | None = None) -> SymbolAvailability:
    return SymbolAvailability(Catalog.from_settings(settings), settings, redis)  # type: ignore[arg-type]


# --- the three answers ---------------------------------------------------


@respx.mock
async def test_a_listed_symbol_is_knowable_on_a_cold_catalog(settings: Settings) -> None:
    # The whole point: nobody has ingested anything, and SOLUSDT is still a
    # valid thing to ask for because the worker can fetch it.
    respx.get(EXCHANGE_INFO).mock(return_value=httpx.Response(200, json=EXCHANGE_INFO_BODY))

    assert SOL in await availability(settings).knowable((SOL,))


@respx.mock
async def test_an_unlisted_symbol_is_not_knowable(settings: Settings) -> None:
    respx.get(EXCHANGE_INFO).mock(return_value=INVALID_SYMBOL)

    # Excluded, so the validator raises SYMBOL_NOT_IN_CATALOG and the caller
    # gets a 422 on submit rather than a job that fails minutes later.
    assert await availability(settings).knowable(("NOTACOIN.BINANCE",)) == []


@respx.mock
async def test_a_venue_with_no_source_is_not_knowable(settings: Settings) -> None:
    assert await availability(settings).knowable(("BTCUSD.KRAKEN",)) == []


# --- what it refuses to spend -------------------------------------------


@respx.mock
async def test_a_symbol_already_held_is_not_looked_up(
    settings: Settings, catalog_with_btc: None
) -> None:
    # No routes mocked: a network call here would raise. The catalog is the
    # cheap answer and must be the first one.
    assert BTC in await availability(settings).knowable((BTC,))


@respx.mock
async def test_a_lookup_is_cached(settings: Settings, redis: fakeredis.aioredis.FakeRedis) -> None:
    route = respx.get(EXCHANGE_INFO).mock(
        return_value=httpx.Response(200, json=EXCHANGE_INFO_BODY)
    )
    subject = availability(settings, redis)

    await subject.knowable((SOL,))
    await subject.knowable((SOL,))

    assert route.call_count == 1


@respx.mock
async def test_a_rejection_is_cached_too(
    settings: Settings, redis: fakeredis.aioredis.FakeRedis
) -> None:
    route = respx.get(EXCHANGE_INFO).mock(return_value=INVALID_SYMBOL)
    subject = availability(settings, redis)

    await subject.knowable(("NOTACOIN.BINANCE",))
    await subject.knowable(("NOTACOIN.BINANCE",))

    assert route.call_count == 1


# --- an outage is not the caller's fault ---------------------------------


@respx.mock
async def test_an_unreachable_venue_allows_the_symbol_through(settings: Settings) -> None:
    # Telling a user their symbol does not exist because Binance is down is
    # both false and an afternoon wasted. Let it through; the worker will fail
    # it with an upstream code if the outage persists.
    respx.get(EXCHANGE_INFO).mock(side_effect=httpx.ConnectError("no route to host"))

    assert SOL in await availability(settings).knowable((SOL,))


@respx.mock
async def test_an_outage_is_not_cached(
    settings: Settings, redis: fakeredis.aioredis.FakeRedis
) -> None:
    route = respx.get(EXCHANGE_INFO).mock(side_effect=httpx.ConnectError("down"))
    subject = availability(settings, redis)

    await subject.knowable((SOL,))
    await subject.knowable((SOL,))

    # Caching "unreachable" would outlive the outage.
    assert route.call_count > 1
