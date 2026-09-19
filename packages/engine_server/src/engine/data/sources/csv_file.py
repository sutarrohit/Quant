"""A market-data source backed by a CSV file.

Added for Phase 4's cross-engine reproduction, where the reference dataset is a
daily equity series that ships with another library rather than something a
crypto exchange will serve.

It exists as a second `MarketDataSource` rather than as a special case inside
``ingest.py`` -- which is what the protocol was introduced for in Step 3. The
same ingest path runs: raw is recorded before transformation, ``ts_event`` is
the bar close, and the quality monitors see the result.

**The instrument is a simplification, and a deliberate one.** GOOG is an
equity; this builds a ``CurrencyPair`` because that is what the catalog and the
strategy already understand. For a reproduction that compares arithmetic
against another engine on a CASH account with our own fee model, the instrument
type changes nothing that is being measured. It would matter for margin,
borrowing or corporate actions, none of which are in scope, and an equities
market would need a real instrument type before anything is trusted.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_trader.model import Bar, BarType
from nautilus_trader.model.instruments import Instrument

from engine.data.instruments import SpotInstrumentSpec
from engine.data.sources import KlinePage
from engine.data.timeframes import NANOS_PER_MILLI, Timeframe
from engine.errors import CsvSourceError

# Column positions after parsing, mirroring the exchange row layout so the
# ingest path does not care which source produced them.
OPEN_TIME, OPEN, HIGH, LOW, CLOSE, VOLUME = range(6)


def _register_ticker(code: str) -> None:
    """Make an equity ticker addressable as a currency, once."""
    from nautilus_trader.model.enums import CurrencyType
    from nautilus_trader.model.objects import Currency

    if Currency.from_str(code, strict=True) is not None:
        return
    Currency.register(
        Currency(
            code=code,
            precision=8,
            iso4217=0,
            name=code,
            currency_type=CurrencyType.CRYPTO,
        )
    )


class CsvSource:
    """Reads OHLCV from a CSV indexed by date.

    Expects a header and a leading date column, which is the shape pandas
    writes and the shape most published datasets arrive in.
    """

    name = "csv"

    def __init__(
        self,
        path: str | Path,
        *,
        symbol: str,
        venue: str,
        base_currency: str,
        quote_currency: str,
        price_increment: Decimal = Decimal("0.01"),
        size_increment: Decimal = Decimal("1"),
        min_notional: Decimal = Decimal("1"),
        register_base_currency: bool = False,
    ) -> None:
        """``register_base_currency`` models an equity ticker as a currency.

        Opt-in and never a default, because it defeats a guard that exists for
        a reason: ``Currency.from_str`` silently invents a currency for any
        string, so a typo would otherwise produce a plausible instrument priced
        to the wrong number of places (D3). Registering ``GOOG`` deliberately is
        a modelling choice; having it happen by accident is the bug that check
        prevents.
        """
        if register_base_currency:
            _register_ticker(base_currency)
        self.path = Path(path)
        self.symbol = symbol
        self.venue = venue
        self._spec = SpotInstrumentSpec(
            symbol=symbol,
            venue=venue,
            base_currency=base_currency,
            quote_currency=quote_currency,
            price_increment=price_increment,
            size_increment=size_increment,
            min_quantity=size_increment,
            max_quantity=Decimal(1_000_000_000),
            min_notional=min_notional,
            # Fees are a mandatory request input, never inferred from a data
            # file (spec section 7.3).
            maker_fee=Decimal(0),
            taker_fee=Decimal(0),
        )

    def fetch_instrument(self, symbol: str) -> SpotInstrumentSpec:
        if symbol != self.symbol:
            raise CsvSourceError(f"this file holds {self.symbol}, not {symbol}")
        return self._spec

    def _rows(self) -> list[list[Any]]:
        if not self.path.exists():
            raise CsvSourceError(f"no such file: {self.path}")

        rows: list[list[Any]] = []
        with self.path.open(newline="") as handle:
            for record in csv.DictReader(handle):
                stamp = next(iter(record.values()))
                try:
                    moment = datetime.fromisoformat(str(stamp)).replace(tzinfo=UTC)
                except ValueError as exc:
                    raise CsvSourceError(f"unparsable date {stamp!r}") from exc
                rows.append(
                    [
                        int(moment.timestamp() * 1000),
                        record["Open"],
                        record["High"],
                        record["Low"],
                        record["Close"],
                        record.get("Volume", "0"),
                    ]
                )
        if not rows:
            raise CsvSourceError(f"{self.path} holds no rows")
        return sorted(rows, key=lambda row: row[OPEN_TIME])

    def fetch_klines(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> Iterator[KlinePage]:
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        rows = [row for row in self._rows() if start_ms <= row[OPEN_TIME] < end_ms]
        if not rows:
            return
        yield KlinePage(
            rows=rows,
            params={
                "symbol": symbol,
                "interval": timeframe.value,
                "startTime": str(start_ms),
                "endTime": str(end_ms - 1),
                "source": str(self.path),
            },
            response_headers={},
        )

    def parse_klines(
        self,
        page: KlinePage,
        instrument: Instrument,
        bar_type: BarType,
        timeframe: Timeframe,
    ) -> list[Bar]:
        """Rows to bars, stamping ``ts_event`` with the bar close.

        The file's date is the bar's *open*, exactly as an exchange reports it,
        so the interval is added here for the same reason it is added for
        Binance (spec section 4.2).
        """
        interval_ns = timeframe.nanoseconds
        return [
            Bar(
                bar_type=bar_type,
                open=instrument.make_price(Decimal(str(row[OPEN]))),
                high=instrument.make_price(Decimal(str(row[HIGH]))),
                low=instrument.make_price(Decimal(str(row[LOW]))),
                close=instrument.make_price(Decimal(str(row[CLOSE]))),
                volume=instrument.make_qty(Decimal(str(row[VOLUME]))),
                ts_event=int(row[OPEN_TIME]) * NANOS_PER_MILLI + interval_ns,
                ts_init=int(row[OPEN_TIME]) * NANOS_PER_MILLI + interval_ns,
            )
            for row in page.rows
        ]

    def close(self) -> None:
        return None
