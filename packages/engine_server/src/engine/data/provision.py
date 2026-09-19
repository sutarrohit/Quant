"""Fetch whatever a backtest needs that the catalog does not already hold.

The catalog used to be filled by hand: a human ran `python -m engine.data.ingest`
before submitting anything, and a spec naming a symbol nobody had ingested was
rejected at submit time. That put a manual step between a user and an answer,
and the step was pure bookkeeping -- the request already says exactly which
instrument, which timeframe and which window it needs.

So the worker fills the gap itself. This module is that step, and it is
deliberately thin: `Catalog.missing_intervals` already computes which ranges are
absent, and `ingest()` already fetches only gaps, records raw before
transforming, and runs the quality monitors. Nothing here re-implements any of
that.

**Where it runs matters.** In the worker, before the run -- never in the HTTP
handler. A cold two-year 1m window is minutes of paging against the venue, and
the handler's contract is that it validates and enqueues (spec section 7.1).

**What it does not do is weaken reproducibility.** Ingest is idempotent: a
window already held is a no-op, and raw responses are append-only. The first run
of a window defines the data; every later run reads the same bars off disk. What
changes is only *when* the fetch happens, not whether the result is stable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from nautilus_trader.model import BarType

from engine.data.catalog import Catalog
from engine.data.ingest import ingest
from engine.data.raw import RawStore
from engine.data.sources import MarketDataSource
from engine.data.sources.binance import BinanceSpotSource
from engine.data.timeframes import NANOS_PER_MILLI, Timeframe
from engine.errors import DataRangeUnavailable, VenueUnsupported
from engine.settings import Settings

logger = logging.getLogger(__name__)

#: Venues this service can fetch for, and how. A venue absent here is not a
#: failure of the strategy -- it is a source nobody has written yet, and the
#: error says so rather than reporting "no data".
SOURCES: dict[str, type[BinanceSpotSource]] = {"BINANCE": BinanceSpotSource}

#: Budget for a single "does this symbol exist" question on the request path.
PROBE_TIMEOUT_SECONDS = 3.0


@dataclass(frozen=True, slots=True)
class ProvisionResult:
    bar_type: str
    fetched: bool
    bars_written: int

    def describe(self) -> str:
        if not self.fetched:
            return f"{self.bar_type}: already in the catalog"
        return f"{self.bar_type}: fetched {self.bars_written} bars"


def _to_ns(moment: datetime) -> int:
    return int(moment.timestamp() * 1_000) * NANOS_PER_MILLI


def _from_ns(nanoseconds: int) -> datetime:
    return datetime.fromtimestamp(nanoseconds / 1e9, tz=UTC)


def source_for(venue: str, settings: Settings, *, probe: bool = False) -> MarketDataSource:
    """The data source for a venue, or a clear error naming it.

    ``probe`` builds one for a single cheap question rather than a long ingest:
    one attempt, a short timeout, no backoff. The patient retry policy is
    correct when paging a two-year window in the worker and wrong on the
    request path, where it would hold an HTTP handler open for the length of a
    venue outage.
    """
    factory = SOURCES.get(venue.upper())
    if factory is None:
        raise VenueUnsupported(
            f"no market-data source for venue {venue!r}; known venues: {', '.join(sorted(SOURCES))}",
            details={"venue": venue},
        )
    if probe:
        return factory(
            client=httpx.Client(timeout=PROBE_TIMEOUT_SECONDS),
            max_attempts=1,
            min_interval_s=0.0,
        )
    return factory()


def ensure_window(
    *,
    bar_type: str,
    start: datetime,
    end: datetime,
    settings: Settings,
    source: MarketDataSource | None = None,
) -> ProvisionResult:
    """Make the catalog able to answer for ``[start, end)``, fetching if it cannot.

    Returns without touching the network when the window is already held, which
    is the common case for every run after the first.
    """
    parsed = BarType.from_str(bar_type)
    instrument_id = parsed.instrument_id
    symbol = instrument_id.symbol.value
    venue = instrument_id.venue.value
    timeframe = Timeframe.from_bar_type(parsed)

    catalog = Catalog.from_settings(settings)
    start_ns, end_ns = _to_ns(start), _to_ns(end)
    # Coverage is asked in CLOSE space, matching `ingest()`: the first bar a
    # window can hold closes one interval after the window opens.
    first_close_ns = start_ns + timeframe.nanoseconds

    if not catalog.missing_intervals(parsed, first_close_ns, end_ns):
        logger.info("window already held", extra={"bar_type": bar_type})
        return ProvisionResult(bar_type, fetched=False, bars_written=0)

    owned_source = source is None
    source = source or source_for(venue, settings)
    logger.info(
        "fetching missing data",
        extra={"bar_type": bar_type, "start": start.isoformat(), "end": end.isoformat()},
    )
    try:
        result = ingest(
            source=source,
            catalog=catalog,
            raw_store=RawStore.from_settings(settings),
            symbol=symbol,
            venue=venue,
            timeframe=timeframe,
            start=start,
            end=end,
        )
    finally:
        if owned_source:
            source.close()

    _assert_covered(catalog, parsed, timeframe, start_ns, end_ns)
    return ProvisionResult(bar_type, fetched=not result.skipped, bars_written=result.bars_written)


def _assert_covered(
    catalog: Catalog,
    bar_type: BarType,
    timeframe: Timeframe,
    start_ns: int,
    end_ns: int,
) -> None:
    """Refuse a window the venue could not fill.

    A shortfall of up to one bar at either end is tolerated, because it is the
    normal shape of a correct answer: a window ending *now* cannot contain a bar
    that has not closed yet. Anything larger means the venue has no such
    history -- the symbol listed later than the request starts, or the window
    runs into the future -- and that is reported rather than quietly traded
    around.
    """
    coverage = catalog.coverage(bar_type)
    if coverage is None:
        raise DataRangeUnavailable(
            f"{bar_type} has no data at the venue for the requested window",
            details={"barType": str(bar_type)},
        )

    tolerance = timeframe.nanoseconds
    held_start_ns, held_end_ns = coverage.start_ns, coverage.end_ns
    wanted_first_close = start_ns + timeframe.nanoseconds

    if held_start_ns > wanted_first_close + tolerance:
        raise DataRangeUnavailable(
            f"{bar_type} has no data before {coverage.start.isoformat()}; "
            f"the request starts at {_from_ns(start_ns).isoformat()}",
            details={
                "barType": str(bar_type),
                "earliestAvailable": coverage.start.isoformat(),
                "requestedStart": _from_ns(start_ns).isoformat(),
            },
        )

    if held_end_ns + tolerance < end_ns:
        raise DataRangeUnavailable(
            f"{bar_type} has no data after {coverage.end.isoformat()}; "
            f"the request ends at {_from_ns(end_ns).isoformat()}",
            details={
                "barType": str(bar_type),
                "latestAvailable": coverage.end.isoformat(),
                "requestedEnd": _from_ns(end_ns).isoformat(),
            },
        )
