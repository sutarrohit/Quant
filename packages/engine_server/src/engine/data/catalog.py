"""Access to the Parquet market-data catalog.

``BacktestNode`` reads a ``ParquetDataCatalog`` directly, so this wrapper is for
ingest and introspection -- it is not a layer the engine goes through. Keeping
it thin is deliberate: anything clever here would apply to ingest but not to a
backtest, and the two would drift.

Storage roots come from ``NT_CATALOG_PATH`` and may be a local path or an
object-storage URI (spec section 3).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Self

from nautilus_trader.model import Bar, BarType
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from engine.errors import CatalogError
from engine.settings import Settings


@dataclass(frozen=True, slots=True)
class BarCoverage:
    """What the catalog actually holds for one bar type."""

    bar_type: str
    start_ns: int
    end_ns: int

    @property
    def start(self) -> datetime:
        return datetime.fromtimestamp(self.start_ns / 1e9, tz=UTC)

    @property
    def end(self) -> datetime:
        return datetime.fromtimestamp(self.end_ns / 1e9, tz=UTC)


class Catalog:
    """Read and write bars and instruments."""

    def __init__(self, root: str) -> None:
        self.root = root
        # from_uri, not the constructor: it resolves a bare local path to a
        # file:// URI and parses s3:// and friends into path + protocol.
        self._catalog = ParquetDataCatalog.from_uri(root)

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(settings.catalog_path)

    def exists(self) -> bool:
        """True when the catalog root is reachable. Backs ``GET /ready``."""
        try:
            return bool(self._catalog.fs.exists(self._catalog.path))
        except Exception:
            # An unreachable object store raises rather than returning False.
            # Readiness is a yes/no question; the reason is logged by the caller.
            return False

    # --- writing ---------------------------------------------------------

    def write_instruments(self, instruments: Sequence[Instrument]) -> None:
        if not instruments:
            return
        self._catalog.write_data(list(instruments))

    def write_bars(self, bars: Sequence[Bar]) -> None:
        """Write bars, rejecting the one invariant that silently ruins a backtest.

        ``ts_init`` is when the platform could first have known the bar, so it
        can never precede the bar's close (spec section 4.2). A bar that
        violates this is visible to a strategy before it happened.

        Gaps, duplicates, outliers and monotonicity are *not* checked here --
        they belong to ``data/quality.py`` (Step 5), which reports on them
        rather than refusing the write.
        """
        if not bars:
            return
        for bar in bars:
            if bar.ts_init < bar.ts_event:
                raise CatalogError(
                    f"ts_init precedes ts_event for {bar.bar_type}: "
                    f"ts_init={bar.ts_init} ts_event={bar.ts_event}",
                )
        self._catalog.write_data(list(bars))

    # --- reading ---------------------------------------------------------

    def read_bars(
        self,
        bar_type: BarType | str,
        *,
        start: int | None = None,
        end: int | None = None,
    ) -> list[Bar]:
        """Bars for one bar type, ordered by ``ts_event``.

        ``start`` and ``end`` are UTC nanoseconds and are both inclusive.
        """
        return self._catalog.bars(bar_types=[str(bar_type)], start=start, end=end)

    def instruments(self) -> list[Instrument]:
        return self._catalog.instruments()

    def instrument_ids(self) -> list[str]:
        return sorted(str(instrument.id) for instrument in self.instruments())

    def bar_types(self) -> list[str]:
        """Every bar type held, sorted.

        Derived from the catalog's own file layout (``data/bar/<bar_type>/``);
        there is no API that lists identifiers. Sorted because unordered output
        would make anything built on it non-deterministic (spec section 12).
        """
        paths: Iterable[str] = self._catalog.get_file_list_from_data_cls(Bar)
        return sorted({PurePosixPath(path).parent.name for path in paths})

    def missing_intervals(
        self,
        bar_type: BarType | str,
        start_ns: int,
        end_ns: int,
    ) -> list[tuple[int, int]]:
        """Sub-ranges of ``[start_ns, end_ns]`` the catalog does not hold.

        Empty means the window is fully covered, which is what makes a
        re-ingest of an already-ingested window a no-op rather than a second
        pass over the exchange API.
        """
        intervals = self._catalog.get_missing_intervals_for_request(
            start_ns, end_ns, Bar, str(bar_type)
        )
        return [(int(start), int(end)) for start, end in intervals]

    def backtestable_instrument_ids(self) -> list[str]:
        """Instruments that actually have bars, derived from the file layout.

        Cheaper than ``instruments()``, which opens parquet, and a better answer
        to "what can be backtested": an instrument definition with no bar data
        cannot be simulated. Used on the request path, where latency matters.
        """
        return sorted({str(BarType.from_str(name).instrument_id) for name in self.bar_types()})

    def coverage(self, bar_type: BarType | str) -> BarCoverage | None:
        """Range held for one bar type, or ``None`` when it holds nothing."""
        identifier = str(bar_type)
        intervals = self._catalog.get_intervals(Bar, identifier)
        if not intervals:
            return None
        return BarCoverage(
            bar_type=identifier,
            start_ns=min(start for start, _ in intervals),
            end_ns=max(end for _, end in intervals),
        )
