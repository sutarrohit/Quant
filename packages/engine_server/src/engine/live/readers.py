"""What the venue holds, and what our cache holds (spec section 10.3).

Startup reconciliation compares two views of an account and refuses to start on
any disagreement. `engine.live.recovery` is the comparison and is pure; these
are the two things it compares, and they are the parts that touch a network and
a database.

**Why this could not be built earlier.** Reading what a venue holds means
private endpoints — open orders, balances, positions — which means a key, which
ADR-001 forbids until its conditions are met. So `CacheReader` and `VenueReader`
stayed protocols with test stubs, and reconciliation was proven against
fabricated snapshots rather than an exchange.

That is a real gap and this closes half of it: the code exists and its shape is
tested against recorded responses. **It has still never run against Binance**,
and it cannot until a key is loaded. Do not read a green test here as evidence
that reconciliation works in production.

**Spot has no positions.** A spot account holds *balances*; a position is a
derivatives idea. So the venue reader reports balances and open orders, and the
cache reader reports the same, and the comparison is between those. A futures
account would add positions, which is why the snapshot type carries them.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from engine.live.recovery import (
    AccountSnapshot,
    BalanceSnapshot,
    OrderSnapshot,
    PositionSnapshot,
)

logger = logging.getLogger(__name__)

#: Binance's order vocabulary is not Nautilus's, and reconciliation compares
#: the words. Binance says `NEW` for an order resting on the book; Nautilus
#: calls that `ACCEPTED`. Left untranslated, **every open order at startup
#: reads as ORDER_STATUS_DIFFERS and the account halts** -- a node refusing to
#: start on its first live run, for a spelling difference.
#:
#: Found by comparing the two readers against each other rather than each
#: against a fixture, which is the only arrangement in which it shows up.
BINANCE_ORDER_STATUS = {
    "NEW": "ACCEPTED",
    "PARTIALLY_FILLED": "PARTIALLY_FILLED",
    "FILLED": "FILLED",
    "CANCELED": "CANCELED",
    "PENDING_CANCEL": "PENDING_CANCEL",
    "REJECTED": "REJECTED",
    "EXPIRED": "EXPIRED",
    "EXPIRED_IN_MATCH": "EXPIRED",
}

#: Balances below this are noise: dust from a fee, a rounding remainder, an
#: airdrop nobody asked for. Comparing them would halt an account over a
#: fraction of a cent it cannot trade anyway.
DUST = Decimal("0.00000001")


def _order_status(binance_status: str) -> str:
    """Translate, and refuse to guess.

    An unmapped status is returned unchanged, so it surfaces as a discrepancy
    and halts the account rather than being silently coerced into something
    that matches. A status this code has never seen is exactly the case where
    starting anyway is wrong.
    """
    mapped = BINANCE_ORDER_STATUS.get(binance_status.upper())
    if mapped is None:
        logger.warning(
            "unmapped venue order status; it will read as a discrepancy",
            extra={"status": binance_status},
        )
        return binance_status
    return mapped


def _decimal(value: Any) -> Decimal:
    """Every number from an exchange arrives as a string, and must stay one.

    `Decimal(float)` is how a balance becomes 0.10000000000000000555 and a
    reconciliation halts an account over nothing (rule 4).
    """
    return Decimal(str(value))


class NautilusCacheReader:
    """What this node believes, read from Nautilus's own cache.

    The cache is the thing that survives a restart -- it is why live requires a
    Redis and a backtest forbids one. After `TradingNode.build()` it has been
    loaded from that Redis, so this reads the state a crashed node left behind.
    """

    def __init__(self, cache: Any, venue: str) -> None:
        self._cache = cache
        self._venue = venue

    async def snapshot(self, account_id: str) -> AccountSnapshot:
        del account_id  # one node per account; the cache is already scoped

        orders = tuple(
            OrderSnapshot(
                client_order_id=str(order.client_order_id),
                instrument_id=str(order.instrument_id),
                side=order.side.name,
                quantity=_decimal(order.quantity),
                status=order.status.name,
            )
            for order in self._cache.orders_open()
        )

        positions = tuple(
            PositionSnapshot(
                instrument_id=str(position.instrument_id),
                quantity=_decimal(position.quantity),
                side=position.side.name,
            )
            for position in self._cache.positions_open()
        )

        balances: tuple[BalanceSnapshot, ...] = ()
        account = self._cache.account_for_venue(_venue(self._venue))
        if account is not None:
            balances = tuple(
                BalanceSnapshot(currency=str(balance.currency), total=_decimal(balance.total))
                for balance in account.balances().values()
                if _decimal(balance.total) > DUST
            )

        return AccountSnapshot(positions=positions, orders=orders, balances=balances)


class BinanceSpotVenueReader:
    """What Binance says the account holds.

    Two private calls, both of which need a key: the account's balances, and
    its open orders. Nothing here places or cancels anything -- a reader that
    could would be a much more interesting thing to get wrong.

    **A spot account has no positions**, so the snapshot's `positions` is always
    empty. That is not an omission: the comparison against the cache is then
    over balances and open orders, which is what a spot account actually has.
    """

    def __init__(self, account_api: Any, *, symbols: tuple[str, ...] = ()) -> None:
        self._api = account_api
        #: Which symbols to ask about. Binance's open-orders endpoint costs far
        #: more weight when asked about every symbol at once, and an account
        #: here trades one instrument.
        self._symbols = symbols

    async def snapshot(self, account_id: str) -> AccountSnapshot:
        del account_id

        info = await self._api.query_spot_account_info()
        balances = tuple(
            BalanceSnapshot(currency=str(entry.asset), total=_decimal(entry.free) + _decimal(entry.locked))
            for entry in info.balances
            if _decimal(entry.free) + _decimal(entry.locked) > DUST
        )

        orders: list[OrderSnapshot] = []
        for symbol in self._symbols or (None,):
            for order in await self._api.query_open_orders(symbol=symbol):
                orders.append(
                    OrderSnapshot(
                        client_order_id=str(order.clientOrderId),
                        instrument_id=f"{order.symbol}.BINANCE",
                        side=str(order.side),
                        quantity=_decimal(order.origQty),
                        status=_order_status(str(order.status)),
                    )
                )

        logger.info(
            "venue snapshot read",
            extra={"balances": len(balances), "open_orders": len(orders)},
        )
        return AccountSnapshot(positions=(), orders=tuple(orders), balances=balances)


def _venue(name: str) -> Any:
    from nautilus_trader.model.identifiers import Venue

    return Venue(name)
