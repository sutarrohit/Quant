"""Startup reconciliation (spec section 10.3).

Before a node subscribes to any data or starts any strategy, it must agree with
the venue about what it holds. The spec's rule is blunt and worth quoting:

    A node that starts trading on stale or unverified state is worse than a
    node that stays down.

So the order is fixed: load the cache, ask the venue, compare, and only on a
clean match start strategies. Any discrepancy halts.

**Halted means halted.** A reconciliation failure is not retried on a loop. The
supervisor restarts a node that crashed, because crashing is a fact about the
process; it does not restart one that disagrees with the venue, because
disagreeing is a fact about the money, and a node that hammers the exchange
every five seconds while wrong is not recovering, it is just wrong faster.
Clearing it is a deliberate act by an operator.

The comparison here is pure, so every shape of disagreement is testable without
a venue, a key, or a network. The fetching sits behind a protocol.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from engine.errors import ReconciliationFailed

logger = logging.getLogger(__name__)

#: Balances drift by fractions between two reads as fees settle. Positions and
#: orders do not, and are compared exactly.
DEFAULT_BALANCE_TOLERANCE = Decimal("0.00000001")


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    instrument_id: str
    quantity: Decimal
    side: str


@dataclass(frozen=True, slots=True)
class OrderSnapshot:
    client_order_id: str
    instrument_id: str
    side: str
    quantity: Decimal
    status: str


@dataclass(frozen=True, slots=True)
class BalanceSnapshot:
    currency: str
    total: Decimal


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    """What one side believes about an account."""

    positions: tuple[PositionSnapshot, ...] = ()
    orders: tuple[OrderSnapshot, ...] = ()
    balances: tuple[BalanceSnapshot, ...] = ()

    @property
    def is_flat(self) -> bool:
        return not self.positions and not self.orders


class Kind(StrEnum):
    POSITION_ONLY_AT_VENUE = "POSITION_ONLY_AT_VENUE"
    POSITION_ONLY_IN_CACHE = "POSITION_ONLY_IN_CACHE"
    POSITION_QUANTITY_DIFFERS = "POSITION_QUANTITY_DIFFERS"
    POSITION_SIDE_DIFFERS = "POSITION_SIDE_DIFFERS"
    ORDER_ONLY_AT_VENUE = "ORDER_ONLY_AT_VENUE"
    ORDER_ONLY_IN_CACHE = "ORDER_ONLY_IN_CACHE"
    ORDER_STATUS_DIFFERS = "ORDER_STATUS_DIFFERS"
    BALANCE_DIFFERS = "BALANCE_DIFFERS"
    BALANCE_ONLY_AT_VENUE = "BALANCE_ONLY_AT_VENUE"


@dataclass(frozen=True, slots=True)
class Discrepancy:
    kind: Kind
    subject: str
    cached: str | None
    observed: str | None

    def describe(self) -> str:
        return f"{self.kind.value} on {self.subject}: cache={self.cached} venue={self.observed}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "subject": self.subject,
            "cached": self.cached,
            "observed": self.observed,
        }


@dataclass(frozen=True, slots=True)
class Reconciliation:
    discrepancies: tuple[Discrepancy, ...] = field(default_factory=tuple)

    @property
    def clean(self) -> bool:
        return not self.discrepancies

    def to_dict(self) -> dict[str, Any]:
        return {
            "clean": self.clean,
            "discrepancies": [item.to_dict() for item in self.discrepancies],
        }


class VenueReader(Protocol):
    """Whatever can say what the venue believes."""

    async def snapshot(self, account_id: str) -> AccountSnapshot: ...


class CacheReader(Protocol):
    """Whatever can say what our cache believes."""

    async def snapshot(self, account_id: str) -> AccountSnapshot: ...


def _by_key[T](items: Iterable[T], key: str) -> dict[str, T]:
    return {str(getattr(item, key)): item for item in items}


def reconcile(
    cached: AccountSnapshot,
    venue: AccountSnapshot,
    *,
    balance_tolerance: Decimal = DEFAULT_BALANCE_TOLERANCE,
) -> Reconciliation:
    """Compare two views of an account. Pure.

    Every difference is reported rather than the first, so an operator sees the
    whole picture instead of fixing one thing and discovering another.
    """
    found: list[Discrepancy] = []
    found.extend(_compare_positions(cached, venue))
    found.extend(_compare_orders(cached, venue))
    found.extend(_compare_balances(cached, venue, balance_tolerance))
    return Reconciliation(tuple(found))


def _compare_positions(cached: AccountSnapshot, venue: AccountSnapshot) -> list[Discrepancy]:
    ours: dict[str, PositionSnapshot] = _by_key(cached.positions, "instrument_id")
    theirs: dict[str, PositionSnapshot] = _by_key(venue.positions, "instrument_id")
    found: list[Discrepancy] = []

    for instrument_id in sorted(set(ours) | set(theirs)):
        mine, yours = ours.get(instrument_id), theirs.get(instrument_id)
        if mine is None and yours is not None:
            # The dangerous one: a position nobody is managing a stop for.
            found.append(
                Discrepancy(Kind.POSITION_ONLY_AT_VENUE, instrument_id, None, str(yours.quantity))
            )
        elif yours is None and mine is not None:
            found.append(
                Discrepancy(Kind.POSITION_ONLY_IN_CACHE, instrument_id, str(mine.quantity), None)
            )
        elif mine is not None and yours is not None:
            if mine.quantity != yours.quantity:
                found.append(
                    Discrepancy(
                        Kind.POSITION_QUANTITY_DIFFERS,
                        instrument_id,
                        str(mine.quantity),
                        str(yours.quantity),
                    )
                )
            if mine.side != yours.side:
                found.append(
                    Discrepancy(Kind.POSITION_SIDE_DIFFERS, instrument_id, mine.side, yours.side)
                )
    return found


def _compare_orders(cached: AccountSnapshot, venue: AccountSnapshot) -> list[Discrepancy]:
    ours: dict[str, OrderSnapshot] = _by_key(cached.orders, "client_order_id")
    theirs: dict[str, OrderSnapshot] = _by_key(venue.orders, "client_order_id")
    found: list[Discrepancy] = []

    for order_id in sorted(set(ours) | set(theirs)):
        mine, yours = ours.get(order_id), theirs.get(order_id)
        if mine is None and yours is not None:
            # An order we do not know about can still fill.
            found.append(Discrepancy(Kind.ORDER_ONLY_AT_VENUE, order_id, None, yours.status))
        elif yours is None and mine is not None:
            found.append(Discrepancy(Kind.ORDER_ONLY_IN_CACHE, order_id, mine.status, None))
        elif mine is not None and yours is not None and mine.status != yours.status:
            found.append(
                Discrepancy(Kind.ORDER_STATUS_DIFFERS, order_id, mine.status, yours.status)
            )
    return found


def _compare_balances(
    cached: AccountSnapshot, venue: AccountSnapshot, tolerance: Decimal
) -> list[Discrepancy]:
    ours: dict[str, BalanceSnapshot] = _by_key(cached.balances, "currency")
    theirs: dict[str, BalanceSnapshot] = _by_key(venue.balances, "currency")
    found: list[Discrepancy] = []

    for currency in sorted(set(ours) | set(theirs)):
        mine, yours = ours.get(currency), theirs.get(currency)
        if mine is None and yours is not None:
            found.append(
                Discrepancy(Kind.BALANCE_ONLY_AT_VENUE, currency, None, str(yours.total))
            )
        elif yours is None and mine is not None:
            # A currency we hold and the venue does not is a discrepancy in the
            # same direction as a missing balance.
            found.append(Discrepancy(Kind.BALANCE_DIFFERS, currency, str(mine.total), None))
        elif mine is not None and yours is not None and abs(mine.total - yours.total) > tolerance:
            found.append(
                Discrepancy(Kind.BALANCE_DIFFERS, currency, str(mine.total), str(yours.total))
            )
    return found


async def ensure_reconciled(
    account_id: str,
    cache: CacheReader,
    venue: VenueReader,
    *,
    balance_tolerance: Decimal = DEFAULT_BALANCE_TOLERANCE,
) -> Reconciliation:
    """Refuse to proceed unless the two views agree.

    The order is the spec's: cache first, venue second, compare third. Asking
    the venue before loading the cache would leave a window in which a fill
    arrives between the two reads and looks like a discrepancy.
    """
    cached = await cache.snapshot(account_id)
    observed = await venue.snapshot(account_id)
    result = reconcile(cached, observed, balance_tolerance=balance_tolerance)

    if result.clean:
        logger.info(
            "reconciled with the venue",
            extra={
                "account_id": account_id,
                "positions": len(observed.positions),
                "orders": len(observed.orders),
            },
        )
        return result

    logger.error(
        "reconciliation failed; refusing to start",
        extra={
            "account_id": account_id,
            "discrepancies": [item.to_dict() for item in result.discrepancies],
        },
    )
    raise ReconciliationFailed(
        f"{account_id} disagrees with the venue on "
        + "; ".join(item.describe() for item in result.discrepancies[:3]),
        details=result.to_dict(),
    )
