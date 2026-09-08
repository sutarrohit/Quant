"""The two things reconciliation compares.

`engine.live.recovery` is pure and was always testable. These are the halves
that touch a network and a cache, and they could not be written until ADR-002
settled and a key became a near-term prospect.

**Tested against recorded shapes, not against Binance.** Every test here uses a
fake with the fields the real client returns. That proves the translation --
strings to `Decimal`, dust filtered, the right fields in the right places --
and proves nothing about whether Binance returns what we think. Read a green
run here as "the code is shaped correctly", never as "reconciliation works".
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from engine.live.readers import DUST, BinanceSpotVenueReader, NautilusCacheReader


class FakeAccount:
    def __init__(self, balances: dict[str, str]) -> None:
        self._balances = {
            currency: SimpleNamespace(currency=currency, total=total)
            for currency, total in balances.items()
        }

    def balances(self) -> dict[str, Any]:
        return self._balances


class FakeCache:
    def __init__(
        self,
        *,
        orders: tuple[Any, ...] = (),
        positions: tuple[Any, ...] = (),
        account: FakeAccount | None = None,
    ) -> None:
        self._orders = orders
        self._positions = positions
        self._account = account

    def orders_open(self) -> tuple[Any, ...]:
        return self._orders

    def positions_open(self) -> tuple[Any, ...]:
        return self._positions

    def account_for_venue(self, venue: Any) -> FakeAccount | None:
        return self._account


def order(**overrides: Any) -> SimpleNamespace:
    payload: dict[str, Any] = {
        "client_order_id": "O-1",
        "instrument_id": "BTCUSDT.BINANCE",
        "side": SimpleNamespace(name="BUY"),
        "quantity": "0.5",
        "status": SimpleNamespace(name="ACCEPTED"),
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


# --- the cache -----------------------------------------------------------


async def test_an_empty_cache_reads_flat() -> None:
    snapshot = await NautilusCacheReader(FakeCache(), "BINANCE").snapshot("acct_1")

    assert snapshot.is_flat
    assert snapshot.balances == ()


async def test_open_orders_are_read() -> None:
    """The state a crashed node left behind.

    This is the whole reason live requires a Redis cache and a backtest forbids
    one -- without it a restart has nothing to compare the venue against.
    """
    cache = FakeCache(orders=(order(),))

    snapshot = await NautilusCacheReader(cache, "BINANCE").snapshot("acct_1")

    assert len(snapshot.orders) == 1
    assert snapshot.orders[0].client_order_id == "O-1"
    assert snapshot.orders[0].quantity == Decimal("0.5")


async def test_quantities_are_decimal_not_float() -> None:
    # Rule 4. `Decimal(float)` is how a balance becomes 0.10000000000000000555
    # and reconciliation halts an account over nothing.
    cache = FakeCache(orders=(order(quantity=0.1),))

    snapshot = await NautilusCacheReader(cache, "BINANCE").snapshot("acct_1")

    assert snapshot.orders[0].quantity == Decimal("0.1")


async def test_balances_are_read_from_the_account() -> None:
    cache = FakeCache(account=FakeAccount({"USDT": "10000.5"}))

    snapshot = await NautilusCacheReader(cache, "BINANCE").snapshot("acct_1")

    assert len(snapshot.balances) == 1
    assert snapshot.balances[0].currency == "USDT"
    assert snapshot.balances[0].total == Decimal("10000.5")


async def test_dust_is_ignored() -> None:
    """A fraction of a cent must not halt an account.

    Fee remainders and airdrops leave balances too small to trade. Comparing
    them would refuse to start over something nobody can act on.
    """
    cache = FakeCache(account=FakeAccount({"USDT": "10000", "SHIB": str(DUST / 2)}))

    snapshot = await NautilusCacheReader(cache, "BINANCE").snapshot("acct_1")

    assert [balance.currency for balance in snapshot.balances] == ["USDT"]


async def test_no_account_yet_is_not_an_error() -> None:
    # A node that has connected but not received its account state reads as
    # having no balances, which the comparison then reports honestly.
    snapshot = await NautilusCacheReader(FakeCache(account=None), "BINANCE").snapshot("a")

    assert snapshot.balances == ()


# --- the venue -----------------------------------------------------------


class FakeAccountApi:
    def __init__(self, balances: list[tuple[str, str, str]], orders: list[Any]) -> None:
        self._balances = [
            SimpleNamespace(asset=asset, free=free, locked=locked)
            for asset, free, locked in balances
        ]
        self._orders = orders
        self.asked: list[str | None] = []

    async def query_spot_account_info(self) -> Any:
        return SimpleNamespace(balances=self._balances)

    async def query_open_orders(self, symbol: str | None = None) -> list[Any]:
        self.asked.append(symbol)
        return self._orders


def venue_order(**overrides: Any) -> SimpleNamespace:
    payload: dict[str, Any] = {
        "clientOrderId": "O-1",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "origQty": "0.5",
        "status": "NEW",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


async def test_free_and_locked_are_summed() -> None:
    """What the account holds, not what it can spend.

    A balance sitting behind an open order is still the account's, and reading
    only `free` would make the venue look poorer than the cache and halt the
    node.
    """
    api = FakeAccountApi([("USDT", "9000", "1000")], [])

    snapshot = await BinanceSpotVenueReader(api).snapshot("acct_1")

    assert snapshot.balances[0].total == Decimal("10000")


async def test_venue_dust_is_ignored() -> None:
    api = FakeAccountApi([("USDT", "10000", "0"), ("SHIB", "0.000000001", "0")], [])

    snapshot = await BinanceSpotVenueReader(api).snapshot("acct_1")

    assert [balance.currency for balance in snapshot.balances] == ["USDT"]


async def test_open_orders_carry_a_nautilus_instrument_id() -> None:
    # The comparison keys on instrument id, so a venue symbol that stayed
    # "BTCUSDT" would never match the cache's "BTCUSDT.BINANCE" and every
    # order would read as only-at-venue.
    api = FakeAccountApi([], [venue_order()])

    snapshot = await BinanceSpotVenueReader(api).snapshot("acct_1")

    assert snapshot.orders[0].instrument_id == "BTCUSDT.BINANCE"


async def test_it_asks_only_about_the_symbols_it_trades() -> None:
    """Binance charges far more request weight for an all-symbol query.

    An account here trades one instrument, so asking about every symbol is
    both slower and a rate limit waiting to happen.
    """
    api = FakeAccountApi([], [])

    await BinanceSpotVenueReader(api, symbols=("BTCUSDT",)).snapshot("acct_1")

    assert api.asked == ["BTCUSDT"]


async def test_with_no_symbols_it_asks_once_for_everything() -> None:
    api = FakeAccountApi([], [])

    await BinanceSpotVenueReader(api).snapshot("acct_1")

    assert api.asked == [None]


async def test_a_spot_account_reports_no_positions() -> None:
    """Not an omission. A spot account holds balances; a position is a
    derivatives idea, and inventing one would make the comparison lie."""
    api = FakeAccountApi([("USDT", "10000", "0")], [venue_order()])

    snapshot = await BinanceSpotVenueReader(api).snapshot("acct_1")

    assert snapshot.positions == ()


# --- the two of them together --------------------------------------------


async def test_agreeing_views_reconcile_clean() -> None:
    from engine.live.recovery import reconcile

    cache = NautilusCacheReader(
        FakeCache(orders=(order(),), account=FakeAccount({"USDT": "10000"})), "BINANCE"
    )
    venue = BinanceSpotVenueReader(
        FakeAccountApi([("USDT", "10000", "0")], [venue_order()]), symbols=("BTCUSDT",)
    )

    result = reconcile(await cache.snapshot("acct_1"), await venue.snapshot("acct_1"))

    assert result.clean, [d.describe() for d in result.discrepancies]


async def test_an_order_only_the_venue_knows_about_is_caught() -> None:
    """The crash between submitting and recording.

    The venue has a working order the cache has never heard of. This is the
    case reconciliation exists for, and now it can be produced from the two
    real readers rather than from a fabricated snapshot.
    """
    from engine.live.recovery import Kind, reconcile

    cache = NautilusCacheReader(FakeCache(account=FakeAccount({"USDT": "10000"})), "BINANCE")
    venue = BinanceSpotVenueReader(
        FakeAccountApi([("USDT", "10000", "0")], [venue_order()]), symbols=("BTCUSDT",)
    )

    result = reconcile(await cache.snapshot("acct_1"), await venue.snapshot("acct_1"))

    assert [d.kind for d in result.discrepancies] == [Kind.ORDER_ONLY_AT_VENUE]


@pytest.mark.parametrize("free,locked", [("9999", "0"), ("10001", "0")])
async def test_a_balance_that_differs_is_caught(free: str, locked: str) -> None:
    from engine.live.recovery import reconcile

    cache = NautilusCacheReader(FakeCache(account=FakeAccount({"USDT": "10000"})), "BINANCE")
    venue = BinanceSpotVenueReader(FakeAccountApi([("USDT", free, locked)], []))

    result = reconcile(await cache.snapshot("a"), await venue.snapshot("a"))

    assert not result.clean


# --- the vocabularies differ ---------------------------------------------


async def test_binance_new_becomes_nautilus_accepted() -> None:
    """The defect this file found.

    Binance says `NEW` for an order resting on the book; Nautilus calls it
    `ACCEPTED`. Untranslated, every open order at startup reads as
    ORDER_STATUS_DIFFERS and the account halts -- a node refusing to start on
    its first live run, over a spelling difference.

    It only shows up when the two readers are compared against each other,
    rather than each against a fixture written by the same hand.
    """
    api = FakeAccountApi([], [venue_order(status="NEW")])

    snapshot = await BinanceSpotVenueReader(api).snapshot("acct_1")

    assert snapshot.orders[0].status == "ACCEPTED"


@pytest.mark.parametrize(
    "binance,nautilus",
    [
        ("NEW", "ACCEPTED"),
        ("PARTIALLY_FILLED", "PARTIALLY_FILLED"),
        ("FILLED", "FILLED"),
        ("CANCELED", "CANCELED"),
        ("REJECTED", "REJECTED"),
        ("EXPIRED", "EXPIRED"),
        ("EXPIRED_IN_MATCH", "EXPIRED"),
    ],
)
async def test_every_mapped_status(binance: str, nautilus: str) -> None:
    api = FakeAccountApi([], [venue_order(status=binance)])

    snapshot = await BinanceSpotVenueReader(api).snapshot("acct_1")

    assert snapshot.orders[0].status == nautilus


async def test_every_mapped_value_is_a_real_nautilus_status() -> None:
    # A typo here would map a status onto a word Nautilus never produces, and
    # the account would halt on every start with no clue why.
    from nautilus_trader.model.enums import OrderStatus

    from engine.live.readers import BINANCE_ORDER_STATUS

    known = {status.name for status in OrderStatus}
    assert set(BINANCE_ORDER_STATUS.values()) <= known


async def test_an_unknown_status_is_not_guessed_at() -> None:
    """Returned unchanged, so it halts the account.

    A status this code has never seen is exactly the case where starting
    anyway is wrong -- coercing it into something that matches would hide a
    venue behaviour nobody has looked at.
    """
    api = FakeAccountApi([], [venue_order(status="SOMETHING_NEW")])

    snapshot = await BinanceSpotVenueReader(api).snapshot("acct_1")

    assert snapshot.orders[0].status == "SOMETHING_NEW"
