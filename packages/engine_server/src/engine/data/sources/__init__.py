"""Exchange data sources.

A second exchange must be a new module here, never an edit to ``ingest.py``.
Spec section 13 (pitfall 6): delisted symbols have to be ingestable, so the
ingestion API must not assume a single live venue.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from nautilus_trader.model import Bar, BarType
from nautilus_trader.model.instruments import Instrument

from engine.data.instruments import SpotInstrumentSpec
from engine.data.timeframes import Timeframe


@dataclass(frozen=True, slots=True)
class KlinePage:
    """One page of OHLCV rows, exactly as the exchange returned them.

    ``rows`` is the untransformed payload. Conversion to Nautilus ``Bar``
    objects happens in Step 4, deliberately not here: this layer's only job is
    to fetch faithfully and record what it fetched.
    """

    rows: list[Any]
    params: dict[str, str]
    response_headers: dict[str, str]


@runtime_checkable
class MarketDataSource(Protocol):
    """What ingest needs from an exchange."""

    name: str

    def fetch_instrument(self, symbol: str) -> SpotInstrumentSpec:
        """Exchange metadata for one symbol: precisions, increments, limits."""
        ...

    def fetch_klines(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> Iterator[KlinePage]:
        """Paged OHLCV over ``[start, end)``, oldest first."""
        ...

    def parse_klines(
        self,
        page: KlinePage,
        instrument: Instrument,
        bar_type: BarType,
        timeframe: Timeframe,
    ) -> list[Bar]:
        """Convert a page into bars, stamping ``ts_event`` with the bar CLOSE.

        Row layout is the exchange's business, which is why this lives on the
        source rather than in ``ingest.py``. Every implementation must satisfy
        ``engine.data.bars.check_bars``.
        """
        ...

    def close(self) -> None:
        """Release the source's connections."""
        ...


__all__ = ["KlinePage", "MarketDataSource"]
