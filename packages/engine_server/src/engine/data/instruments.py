"""Construct Nautilus instruments from exchange metadata.

Spec section 4.1(3): ingestion builds the *real* instrument from what the
exchange reports -- price precision, size precision, tick size, lot size, min
notional. ``TestInstrumentProvider`` stays confined to tests.

Precision is load-bearing and fails late. If size precision is wrong, position
sizing rounds differently from the way the venue rounds, and the discrepancy
does not surface until orders are compared against real fills.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nautilus_trader.model import InstrumentId, Price, Quantity, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Currency, Money

from engine.errors import EngineError, ErrorCode


class InstrumentError(EngineError):
    code = ErrorCode.INSTRUMENT_INVALID
    http_status = 422


def precision_of(increment: Decimal) -> int:
    """Decimal places implied by a tick or step size.

    Exchanges report increments (``"0.00001000"``), while Nautilus wants both
    the increment and its precision. Deriving one from the other keeps them
    consistent -- ``0.00001000`` is 5 places, not the 8 its trailing zeros
    suggest.
    """
    normalised = increment.normalize()
    exponent = normalised.as_tuple().exponent
    if not isinstance(exponent, int):
        raise InstrumentError(f"increment is not a finite decimal: {increment}")
    return max(0, -exponent)


@dataclass(frozen=True, slots=True)
class SpotInstrumentSpec:
    """Exchange metadata for one spot pair, as Decimals parsed from strings.

    Every monetary field is ``Decimal`` end to end (spec section 12). A float
    here is unrecoverable once it has rounded a stored quantity.
    """

    symbol: str
    venue: str
    base_currency: str
    quote_currency: str
    price_increment: Decimal
    size_increment: Decimal
    min_quantity: Decimal
    max_quantity: Decimal
    min_notional: Decimal
    maker_fee: Decimal
    taker_fee: Decimal


def _currency(code: str) -> Currency:
    """Look up a currency, refusing to invent one.

    ``Currency.from_str(code)`` does *not* raise on an unknown code -- it
    fabricates a CRYPTO currency with precision 8 and returns it. A typo in
    exchange metadata would therefore produce a plausible-looking instrument
    priced to the wrong number of places. ``strict=True`` returns ``None``
    instead, which is what makes this check possible.
    """
    currency = Currency.from_str(code, strict=True)
    if currency is None:
        raise InstrumentError(f"unknown currency: {code!r}")
    return currency


def build_spot_instrument(spec: SpotInstrumentSpec, *, ts_init: int = 0) -> CurrencyPair:
    """Build a ``CurrencyPair`` from exchange metadata.

    ``ts_init`` defaults to 0 so a re-ingest of the same instrument produces a
    byte-identical record. A wall-clock timestamp here would make the catalog
    differ between runs and break the determinism guarantee (spec section 12).
    """
    if spec.price_increment <= 0 or spec.size_increment <= 0:
        raise InstrumentError(
            f"increments must be positive for {spec.symbol}: "
            f"price={spec.price_increment} size={spec.size_increment}",
        )
    if spec.min_quantity > spec.max_quantity:
        raise InstrumentError(
            f"min_quantity exceeds max_quantity for {spec.symbol}: "
            f"{spec.min_quantity} > {spec.max_quantity}",
        )

    price_precision = precision_of(spec.price_increment)
    size_precision = precision_of(spec.size_increment)
    quote = _currency(spec.quote_currency)

    return CurrencyPair(
        instrument_id=InstrumentId(symbol=Symbol(spec.symbol), venue=Venue(spec.venue)),
        raw_symbol=Symbol(spec.symbol),
        base_currency=_currency(spec.base_currency),
        quote_currency=quote,
        price_precision=price_precision,
        size_precision=size_precision,
        price_increment=Price(spec.price_increment, precision=price_precision),
        size_increment=Quantity(spec.size_increment, precision=size_precision),
        lot_size=None,
        max_quantity=Quantity(spec.max_quantity, precision=size_precision),
        min_quantity=Quantity(spec.min_quantity, precision=size_precision),
        max_notional=None,
        min_notional=Money(spec.min_notional, quote),
        max_price=None,
        min_price=None,
        margin_init=Decimal(0),
        margin_maint=Decimal(0),
        maker_fee=spec.maker_fee,
        taker_fee=spec.taker_fee,
        ts_event=0,
        ts_init=ts_init,
    )


__all__ = [
    "InstrumentError",
    "SpotInstrumentSpec",
    "build_spot_instrument",
    "precision_of",
]
