from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from engine.data.instruments import (
    InstrumentError,
    SpotInstrumentSpec,
    build_spot_instrument,
    precision_of,
)


@pytest.mark.parametrize(
    ("increment", "precision"),
    [
        ("1", 0),
        ("0.1", 1),
        ("0.01", 2),
        ("0.00001", 5),
        # Exchanges pad increments with trailing zeros. 0.00001000 is 5 places,
        # not 8 -- taking the string length would over-state precision.
        ("0.00001000", 5),
        ("1.00000000", 0),
        ("10", 0),
    ],
)
def test_precision_is_derived_from_the_increment(increment: str, precision: int) -> None:
    assert precision_of(Decimal(increment)) == precision


def test_builds_a_spot_instrument(spot_spec: SpotInstrumentSpec) -> None:
    instrument = build_spot_instrument(spot_spec)

    assert str(instrument.id) == "BTCUSDT.BINANCE"
    assert instrument.price_precision == 2
    assert instrument.size_precision == 5
    assert instrument.price_increment == Decimal("0.01")
    assert instrument.size_increment == Decimal("0.00001")
    assert instrument.min_notional.as_decimal() == Decimal("10")
    assert instrument.maker_fee == Decimal("0.001")
    assert instrument.taker_fee == Decimal("0.001")


def test_precision_follows_the_exchange_not_a_default(spot_spec: SpotInstrumentSpec) -> None:
    # A venue with coarser ticks must not inherit BTCUSDT's precision: sizing
    # would round finer than the venue accepts and orders would be rejected.
    coarse = replace(
        spot_spec,
        symbol="DOGEUSDT",
        base_currency="DOGE",
        price_increment=Decimal("0.00001"),
        size_increment=Decimal("1"),
    )
    instrument = build_spot_instrument(coarse)
    assert instrument.price_precision == 5
    assert instrument.size_precision == 0


def test_is_deterministic_across_builds(spot_spec: SpotInstrumentSpec) -> None:
    # Spec section 12: a re-ingest must not produce a different record, so
    # ts_init defaults to 0 rather than a wall clock.
    first = build_spot_instrument(spot_spec)
    second = build_spot_instrument(spot_spec)
    assert first.ts_init == 0
    assert first.ts_event == 0
    assert first == second


def test_rejects_a_non_positive_price_increment(spot_spec: SpotInstrumentSpec) -> None:
    with pytest.raises(InstrumentError, match="increments must be positive"):
        build_spot_instrument(replace(spot_spec, price_increment=Decimal("0")))


def test_rejects_a_non_positive_size_increment(spot_spec: SpotInstrumentSpec) -> None:
    with pytest.raises(InstrumentError, match="increments must be positive"):
        build_spot_instrument(replace(spot_spec, size_increment=Decimal("-1")))


def test_rejects_inverted_quantity_bounds(spot_spec: SpotInstrumentSpec) -> None:
    with pytest.raises(InstrumentError, match="min_quantity exceeds max_quantity"):
        build_spot_instrument(
            replace(spot_spec, min_quantity=Decimal("100"), max_quantity=Decimal("1"))
        )


def test_rejects_an_unknown_currency(spot_spec: SpotInstrumentSpec) -> None:
    # Currency.from_str() without strict=True invents a CRYPTO currency with
    # precision 8 for any string, so a typo would price an instrument to the
    # wrong number of places and never complain.
    with pytest.raises(InstrumentError, match="unknown currency"):
        build_spot_instrument(replace(spot_spec, quote_currency="NOTACURRENCY"))
    with pytest.raises(InstrumentError, match="unknown currency"):
        build_spot_instrument(replace(spot_spec, base_currency="ALSOFAKE"))


def test_spec_fields_are_decimal_not_float(spot_spec: SpotInstrumentSpec) -> None:
    # Spec section 12 / rule 4: float money is silent, cumulative and
    # unrecoverable once it has rounded a stored quantity.
    for field in (
        spot_spec.price_increment,
        spot_spec.size_increment,
        spot_spec.min_quantity,
        spot_spec.max_quantity,
        spot_spec.min_notional,
        spot_spec.maker_fee,
        spot_spec.taker_fee,
    ):
        assert isinstance(field, Decimal)


def test_spec_is_frozen(spot_spec: SpotInstrumentSpec) -> None:
    with pytest.raises(AttributeError):
        spot_spec.symbol = "ETHUSDT"  # type: ignore[misc]
