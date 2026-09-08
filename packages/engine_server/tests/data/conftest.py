"""Fixtures for catalog and ingest tests. No network in any of them."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from nautilus_trader.model import Bar, BarType, Price, Quantity
from nautilus_trader.model.instruments import CurrencyPair

from engine.data.catalog import Catalog
from engine.data.instruments import SpotInstrumentSpec, build_spot_instrument

FIFTEEN_MIN_NS = 15 * 60 * 1_000_000_000

# First bar CLOSE, not open. Spec section 4.2.
FIRST_CLOSE_NS = pd.Timestamp("2024-01-01T00:15:00Z").value


@pytest.fixture
def spot_spec() -> SpotInstrumentSpec:
    return SpotInstrumentSpec(
        symbol="BTCUSDT",
        venue="BINANCE",
        base_currency="BTC",
        quote_currency="USDT",
        price_increment=Decimal("0.01"),
        size_increment=Decimal("0.00001"),
        min_quantity=Decimal("0.00001"),
        max_quantity=Decimal("9000"),
        min_notional=Decimal("10"),
        maker_fee=Decimal("0.001"),
        taker_fee=Decimal("0.001"),
    )


@pytest.fixture
def instrument(spot_spec: SpotInstrumentSpec) -> CurrencyPair:
    return build_spot_instrument(spot_spec)


@pytest.fixture
def bar_type(instrument: CurrencyPair) -> BarType:
    return BarType.from_str(f"{instrument.id}-15-MINUTE-LAST-EXTERNAL")


@pytest.fixture
def make_bars(bar_type: BarType) -> Callable[..., list[Bar]]:
    def _make(count: int, *, start_ns: int = FIRST_CLOSE_NS, ts_init_offset: int = 0) -> list[Bar]:
        bars = []
        for index in range(count):
            ts_event = start_ns + index * FIFTEEN_MIN_NS
            price = 40000 + index
            bars.append(
                Bar(
                    bar_type=bar_type,
                    open=Price.from_str(f"{price}.00"),
                    high=Price.from_str(f"{price + 10}.00"),
                    low=Price.from_str(f"{price - 10}.00"),
                    close=Price.from_str(f"{price + 5}.00"),
                    volume=Quantity.from_str("1.00000"),
                    ts_event=ts_event,
                    ts_init=ts_event + ts_init_offset,
                )
            )
        return bars

    return _make


@pytest.fixture
def catalog(tmp_path: Path) -> Catalog:
    return Catalog(str(tmp_path / "catalog"))
