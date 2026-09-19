"""Ingest exchange OHLCV into the Parquet catalog.

    uv run python -m engine.data.ingest \\
      --exchange binance --symbol BTCUSDT --market spot \\
      --timeframe 15m --start 2023-01-01 --end 2025-01-01

The order of operations is fixed by spec section 4.1 and is not an
implementation detail:

1. Fetch a page from the exchange.
2. **Persist the raw response before transforming it.** If step 3 has a bug,
   the evidence still exists. Raw is the audit trail.
3. Convert to Nautilus bars, stamping ``ts_event`` with the bar close.
4. Check timestamp discipline. A violation aborts the run.
5. Write to the catalog.

Re-ingesting a window already held is a no-op: the catalog is asked what it is
missing, and only those ranges are fetched.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from nautilus_trader.model import BarType

from engine.data.bars import check_bars
from engine.data.catalog import Catalog
from engine.data.instruments import build_spot_instrument
from engine.data.quality import QualityReport, check_quality, write_report
from engine.data.raw import RawRecord, RawStore
from engine.data.sources import MarketDataSource
from engine.data.sources.binance import BinanceSpotSource
from engine.data.timeframes import NANOS_PER_MILLI, Timeframe
from engine.errors import EngineError, IngestError, QualityError
from engine.logging import configure_logging, log_context
from engine.settings import Settings, get_settings

logger = logging.getLogger(__name__)

EXCHANGES = {"binance": BinanceSpotSource}
MARKETS = {"spot"}
VENUES = {"binance": "BINANCE"}


@dataclass(frozen=True, slots=True)
class IngestResult:
    bar_type: str
    bars_written: int
    pages_fetched: int
    raw_paths: list[str]
    skipped: bool
    quality: QualityReport | None = None
    quality_path: str | None = None

    def describe(self) -> str:
        if self.skipped:
            return f"{self.bar_type}: already covered, nothing fetched"
        summary = (
            f"{self.bar_type}: {self.bars_written} bars from "
            f"{self.pages_fetched} page(s), {len(self.raw_paths)} raw file(s)"
        )
        if self.quality is not None:
            summary += f"\n  quality: {self.quality.describe()}"
        if self.quality_path is not None:
            summary += f"\n  report:  {self.quality_path}"
        return summary


def parse_day(value: str) -> datetime:
    """Parse a CLI date as UTC midnight.

    Accepts ``2023-01-01`` and full ISO-8601. A naive datetime is treated as
    UTC rather than local time -- a local-time window would ingest a different
    range on a different machine.
    """
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise IngestError(f"could not parse date {value!r}; expected YYYY-MM-DD") from exc
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _to_ns(moment: datetime) -> int:
    return int(moment.timestamp() * 1_000) * NANOS_PER_MILLI


def _from_ns(nanoseconds: int) -> datetime:
    return datetime.fromtimestamp(nanoseconds / 1e9, tz=UTC)


def _fetch_window(missing: tuple[int, int], interval_ns: int) -> tuple[int, int] | None:
    """Turn a missing CLOSE range into the OPEN window that produces it.

    The catalog reports gaps in close space, bounded one nanosecond short of
    the neighbouring stored data. Both ends must be snapped to the bar grid:

    * the first needed close is ``missing_start`` rounded **up**; the bar
      producing it opens one interval earlier, and that is where fetching
      starts.
    * the last needed close is ``missing_end`` rounded **down**. Without this,
      a gap ending just before existing data still fetches the bar that closes
      *at* that data's first timestamp -- and the catalog rejects the write for
      overlapping an existing file.

    Returns ``None`` when the gap is too narrow to hold a whole bar.
    """
    missing_start, missing_end = missing
    first_close = -(-missing_start // interval_ns) * interval_ns
    last_close = (missing_end // interval_ns) * interval_ns
    if first_close > last_close:
        return None
    # fetch_klines takes opens over [start, end); ending at last_close makes
    # the final open last_close - interval, which closes exactly at last_close.
    return first_close - interval_ns, last_close


def ingest(
    *,
    source: MarketDataSource,
    catalog: Catalog,
    raw_store: RawStore,
    symbol: str,
    venue: str,
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
    dry_run: bool = False,
    force: bool = False,
    artifact_path: str | None = None,
) -> IngestResult:
    if start >= end:
        raise IngestError(f"start must precede end, got {start.isoformat()} .. {end.isoformat()}")

    bar_type = BarType.from_str(f"{symbol}.{venue}-{timeframe.aggregation}-LAST-EXTERNAL")
    start_ns, end_ns = _to_ns(start), _to_ns(end)

    # Coverage is checked in CLOSE space, not open space. The window
    # [00:00, 01:00) of 15m bars holds bars closing at 00:15..01:00, so asking
    # whether [00:00, 01:00] is covered always reports the first interval
    # missing and re-fetches a window already fully ingested.
    first_close_ns = start_ns + timeframe.nanoseconds

    if force:
        windows = [(start_ns, end_ns)]
    else:
        missing = catalog.missing_intervals(bar_type, first_close_ns, end_ns)
        if not missing:
            logger.info("window already covered, skipping", extra={"bar_type": str(bar_type)})
            return IngestResult(str(bar_type), 0, 0, [], skipped=True)
        # Only the gaps are fetched. Re-fetching the whole window would also
        # rewrite bars already held, and the catalog rejects a write whose
        # interval overlaps an existing file.
        windows = [
            window
            for window in (_fetch_window(gap, timeframe.nanoseconds) for gap in missing)
            if window is not None
        ]
        if not windows:
            logger.info("gaps hold no whole bar, skipping", extra={"bar_type": str(bar_type)})
            return IngestResult(str(bar_type), 0, 0, [], skipped=True)
        logger.info(
            "window partially covered",
            extra={"bar_type": str(bar_type), "missing_ranges": len(windows)},
        )

    spec = source.fetch_instrument(symbol)
    instrument = build_spot_instrument(spec)
    logger.info(
        "resolved instrument",
        extra={
            "instrument_id": str(instrument.id),
            "price_precision": instrument.price_precision,
            "size_precision": instrument.size_precision,
        },
    )

    raw_paths: list[str] = []
    total_bars = 0
    pages = 0

    for window_start_ns, window_end_ns in windows:
        for page in source.fetch_klines(
            symbol, timeframe, _from_ns(window_start_ns), _from_ns(window_end_ns)
        ):
            pages += 1

            # Raw first. If the conversion below is wrong, this is the evidence.
            raw_paths.append(
                raw_store.write(
                    RawRecord(
                        source=source.name,
                        endpoint="klines",
                        key=f"{symbol}-{timeframe.value}-{page.params['startTime']}-{page.params['endTime']}",
                        params=page.params,
                        payload=page.rows,
                        response_headers={
                            "x-mbx-used-weight-1m": page.response_headers.get("x-mbx-used-weight-1m", ""),
                        },
                    )
                )
            )

            bars = source.parse_klines(page, instrument, bar_type, timeframe)
            # window_start_ns is what catches a dropped open-to-close correction.
            check_bars(bars, timeframe, window_start_ns=window_start_ns)

            if not dry_run:
                catalog.write_bars(bars)
            total_bars += len(bars)
            logger.info(
                "page ingested",
                extra={"page": pages, "bars": len(bars), "dry_run": dry_run},
            )

    if not dry_run and total_bars:
        catalog.write_instruments([instrument])

    # Spec section 4.3: quality runs automatically after every ingest, over the
    # whole stored range rather than one page, so a problem spanning a page
    # boundary is still visible.
    stored = catalog.read_bars(bar_type, start=first_close_ns, end=end_ns) if not dry_run else []
    report = check_quality(stored, timeframe)
    report_path = write_report(report, artifact_path) if artifact_path and stored else None

    if report.failed:
        # Duplicate or backwards timestamps mean the series contradicts itself.
        raise QualityError(
            f"{bar_type} failed quality checks: "
            + "; ".join(finding.message for finding in report.failures[:3]),
            details={"report_path": report_path, "counts": report.counts},
        )

    logger.info(
        "quality checked",
        extra={"bar_type": str(bar_type), "bars": report.bar_count, "counts": report.counts},
    )
    return IngestResult(
        str(bar_type), total_bars, pages, raw_paths, skipped=False,
        quality=report, quality_path=report_path,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m engine.data.ingest",
        description="Ingest exchange OHLCV into the Parquet catalog.",
    )
    parser.add_argument("--exchange", required=True, choices=sorted(EXCHANGES))
    parser.add_argument("--symbol", required=True, help="Exchange symbol, e.g. BTCUSDT")
    parser.add_argument("--market", required=True, choices=sorted(MARKETS))
    parser.add_argument("--timeframe", required=True, choices=[tf.value for tf in Timeframe])
    parser.add_argument("--start", required=True, help="UTC start, e.g. 2023-01-01")
    parser.add_argument("--end", required=True, help="UTC end (exclusive), e.g. 2025-01-01")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch, convert and check, but do not write to the catalog. Raw is still recorded.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch even when the catalog already covers the window.",
    )
    return parser


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    source = EXCHANGES[args.exchange]()
    try:
        with log_context(exchange=args.exchange, symbol=args.symbol, timeframe=args.timeframe):
            result = ingest(
                source=source,
                catalog=Catalog.from_settings(settings),
                raw_store=RawStore.from_settings(settings),
                symbol=args.symbol,
                venue=VENUES[args.exchange],
                timeframe=Timeframe(args.timeframe),
                start=parse_day(args.start),
                end=parse_day(args.end),
                dry_run=args.dry_run,
                force=args.force,
                artifact_path=settings.artifact_path,
            )
    except EngineError as exc:
        logger.error("ingest failed", extra={"code": exc.code.value, "detail": exc.message})
        print(f"{exc.code.value}: {exc.message}", file=sys.stderr)
        return 1
    finally:
        source.close()

    print(result.describe())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
