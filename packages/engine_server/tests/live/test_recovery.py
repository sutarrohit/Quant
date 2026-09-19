"""Startup reconciliation (spec section 10.3).

The comparison is pure, so every shape of disagreement is tested without a
venue, a key, or a network — which matters, because these are the cases that
occur when something has already gone wrong.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from engine.errors import ReconciliationFailed
from engine.live.recovery import (
    AccountSnapshot,
    BalanceSnapshot,
    Kind,
    OrderSnapshot,
    PositionSnapshot,
    ensure_reconciled,
    reconcile,
)

BTC = "BTCUSDT.BINANCE"


def position(quantity: str = "0.5", side: str = "LONG", instrument: str = BTC) -> PositionSnapshot:
    return PositionSnapshot(instrument_id=instrument, quantity=D(quantity), side=side)


def order(order_id: str = "O-1", status: str = "ACCEPTED") -> OrderSnapshot:
    return OrderSnapshot(
        client_order_id=order_id, instrument_id=BTC, side="BUY", quantity=D("0.5"), status=status
    )


def balance(total: str = "10000", currency: str = "USDT") -> BalanceSnapshot:
    return BalanceSnapshot(currency=currency, total=D(total))


def snapshot(**overrides: object) -> AccountSnapshot:
    return AccountSnapshot(**overrides)  # type: ignore[arg-type]


class Reader:
    def __init__(self, state: AccountSnapshot) -> None:
        self._state = state

    async def snapshot(self, account_id: str) -> AccountSnapshot:
        return self._state


# --- agreement -----------------------------------------------------------


def test_two_flat_accounts_agree() -> None:
    assert reconcile(snapshot(), snapshot()).clean is True


def test_identical_state_agrees() -> None:
    state = snapshot(
        positions=(position(),), orders=(order(),), balances=(balance(),)
    )
    assert reconcile(state, state).clean is True


# --- positions -----------------------------------------------------------


def test_a_position_only_at_the_venue_is_a_discrepancy() -> None:
    """The dangerous one.

    A position the node does not know about is a position whose stop nobody is
    managing.
    """
    result = reconcile(snapshot(), snapshot(positions=(position(),)))

    assert [d.kind for d in result.discrepancies] == [Kind.POSITION_ONLY_AT_VENUE]
    assert result.discrepancies[0].observed == "0.5"


def test_a_position_only_in_the_cache_is_a_discrepancy() -> None:
    # We believe we hold something we do not. Trading on that would size the
    # next order against a position that is not there.
    result = reconcile(snapshot(positions=(position(),)), snapshot())
    assert [d.kind for d in result.discrepancies] == [Kind.POSITION_ONLY_IN_CACHE]


def test_a_differing_quantity_is_a_discrepancy() -> None:
    result = reconcile(
        snapshot(positions=(position("0.5"),)), snapshot(positions=(position("0.4"),))
    )
    assert [d.kind for d in result.discrepancies] == [Kind.POSITION_QUANTITY_DIFFERS]
    assert (result.discrepancies[0].cached, result.discrepancies[0].observed) == ("0.5", "0.4")


def test_a_differing_side_is_a_discrepancy() -> None:
    result = reconcile(
        snapshot(positions=(position(side="LONG"),)),
        snapshot(positions=(position(side="SHORT"),)),
    )
    assert Kind.POSITION_SIDE_DIFFERS in [d.kind for d in result.discrepancies]


def test_positions_are_compared_exactly() -> None:
    # No tolerance: a fraction of a coin is still a coin.
    result = reconcile(
        snapshot(positions=(position("0.50000001"),)),
        snapshot(positions=(position("0.50000000"),)),
    )
    assert result.clean is False


# --- orders --------------------------------------------------------------


def test_an_order_only_at_the_venue_is_a_discrepancy() -> None:
    # An order we do not know about can still fill.
    result = reconcile(snapshot(), snapshot(orders=(order(),)))
    assert [d.kind for d in result.discrepancies] == [Kind.ORDER_ONLY_AT_VENUE]


def test_an_order_only_in_the_cache_is_a_discrepancy() -> None:
    result = reconcile(snapshot(orders=(order(),)), snapshot())
    assert [d.kind for d in result.discrepancies] == [Kind.ORDER_ONLY_IN_CACHE]


def test_a_differing_order_status_is_a_discrepancy() -> None:
    result = reconcile(
        snapshot(orders=(order(status="ACCEPTED"),)),
        snapshot(orders=(order(status="FILLED"),)),
    )
    assert [d.kind for d in result.discrepancies] == [Kind.ORDER_STATUS_DIFFERS]


# --- balances ------------------------------------------------------------


def test_a_tiny_balance_difference_is_tolerated() -> None:
    # Fees settle between two reads; positions and orders do not drift.
    result = reconcile(
        snapshot(balances=(balance("10000.00000000"),)),
        snapshot(balances=(balance("10000.000000001"),)),
    )
    assert result.clean is True


def test_a_real_balance_difference_is_a_discrepancy() -> None:
    result = reconcile(
        snapshot(balances=(balance("10000"),)), snapshot(balances=(balance("9500"),))
    )
    assert [d.kind for d in result.discrepancies] == [Kind.BALANCE_DIFFERS]


def test_the_tolerance_is_configurable() -> None:
    pair = (snapshot(balances=(balance("10000"),)), snapshot(balances=(balance("9999"),)))
    assert reconcile(*pair).clean is False
    assert reconcile(*pair, balance_tolerance=D(10)).clean is True


def test_a_currency_only_at_the_venue_is_a_discrepancy() -> None:
    result = reconcile(snapshot(), snapshot(balances=(balance("1", "BTC"),)))
    assert [d.kind for d in result.discrepancies] == [Kind.BALANCE_ONLY_AT_VENUE]


# --- reporting -----------------------------------------------------------


def test_every_discrepancy_is_reported() -> None:
    # An operator seeing one problem, fixing it, and finding another is a worse
    # experience than seeing all of them at once.
    result = reconcile(
        snapshot(positions=(position(),), orders=(order(),), balances=(balance("10000"),)),
        snapshot(balances=(balance("9000"),)),
    )
    assert {d.kind for d in result.discrepancies} == {
        Kind.POSITION_ONLY_IN_CACHE,
        Kind.ORDER_ONLY_IN_CACHE,
        Kind.BALANCE_DIFFERS,
    }


def test_the_result_serialises() -> None:
    result = reconcile(snapshot(), snapshot(positions=(position(),)))
    document = result.to_dict()
    assert document["clean"] is False
    assert document["discrepancies"][0]["kind"] == "POSITION_ONLY_AT_VENUE"


# --- the gate ------------------------------------------------------------


async def test_a_clean_reconciliation_proceeds() -> None:
    state = snapshot(positions=(position(),), balances=(balance(),))
    result = await ensure_reconciled("acct_1", Reader(state), Reader(state))
    assert result.clean is True


async def test_a_disagreement_refuses_to_proceed() -> None:
    """A node that starts trading on unverified state is worse than one that
    stays down."""
    with pytest.raises(ReconciliationFailed) as caught:
        await ensure_reconciled(
            "acct_1", Reader(snapshot()), Reader(snapshot(positions=(position(),)))
        )

    assert caught.value.code.value == "RECONCILIATION_FAILED"
    assert caught.value.details is not None
    assert caught.value.details["clean"] is False


async def test_the_failure_names_the_discrepancies() -> None:
    with pytest.raises(ReconciliationFailed, match="POSITION_ONLY_AT_VENUE"):
        await ensure_reconciled(
            "acct_1", Reader(snapshot()), Reader(snapshot(positions=(position(),)))
        )
