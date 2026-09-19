from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from nautilus_trader.model import BarType

from engine.data.catalog import Catalog
from engine.data.ingest import ingest, main, parse_day
from engine.data.raw import RawStore
from engine.data.sources.binance import BinanceSpotSource
from engine.data.timeframes import NANOS_PER_MILLI, Timeframe
from engine.errors import IngestError, TimestampDisciplineError
from engine.settings import Settings
from tests.data.test_binance import EXCHANGE_INFO, EXCHANGE_INFO_BODY, KLINES, kline

FIFTEEN_MIN_MS = 900_000
START = datetime(2024, 1, 1, tzinfo=UTC)
END = datetime(2024, 1, 1, 1, tzinfo=UTC)
START_MS = int(START.timestamp() * 1000)
BAR_TYPE = "BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL"


def one_hour_rows() -> list[list[Any]]:
    return [kline(START_MS + i * FIFTEEN_MIN_MS) for i in range(4)]


def mock_binance(rows: list[list[Any]] | None = None) -> None:
    respx.get(EXCHANGE_INFO).mock(return_value=httpx.Response(200, json=EXCHANGE_INFO_BODY))
    respx.get(KLINES).mock(
        side_effect=[
            httpx.Response(200, json=one_hour_rows() if rows is None else rows),
            httpx.Response(200, json=[]),
        ]
    )


@pytest.fixture
def source() -> BinanceSpotSource:
    return BinanceSpotSource(client=httpx.Client(), min_interval_s=0.0, sleep=lambda _: None)


@pytest.fixture
def stores(tmp_path: Path) -> tuple[Catalog, RawStore]:
    return Catalog(str(tmp_path / "catalog")), RawStore(str(tmp_path / "raw"))


def run(source: BinanceSpotSource, stores: tuple[Catalog, RawStore], **kwargs: Any) -> Any:
    catalog, raw_store = stores
    return ingest(
        source=source,
        catalog=catalog,
        raw_store=raw_store,
        symbol="BTCUSDT",
        venue="BINANCE",
        timeframe=Timeframe.M15,
        start=START,
        end=END,
        **kwargs,
    )


# --- the headline: bars land close-aligned ------------------------------


@respx.mock
def test_ingested_bars_are_close_stamped(
    source: BinanceSpotSource, stores: tuple[Catalog, RawStore]
) -> None:
    catalog, _ = stores
    mock_binance()

    result = run(source, stores)

    assert result.bars_written == 4
    bars = catalog.read_bars(BAR_TYPE)
    # Binance's first row opens at START. Its bar CLOSES one interval later.
    expected_first_close = (START_MS + FIFTEEN_MIN_MS) * NANOS_PER_MILLI
    assert bars[0].ts_event == expected_first_close
    assert [b.ts_event for b in bars] == [
        expected_first_close + i * Timeframe.M15.nanoseconds for i in range(4)
    ]


@respx.mock
def test_ingested_bars_have_ts_init_equal_to_ts_event(
    source: BinanceSpotSource, stores: tuple[Catalog, RawStore]
) -> None:
    catalog, _ = stores
    mock_binance()
    run(source, stores)
    assert all(bar.ts_init == bar.ts_event for bar in catalog.read_bars(BAR_TYPE))


@respx.mock
def test_prices_are_quantized_by_the_instrument(
    source: BinanceSpotSource, stores: tuple[Catalog, RawStore]
) -> None:
    # Binance sends 8 decimals; BTCUSDT prices are precision 2 and sizes 5.
    catalog, _ = stores
    rows = [kline(START_MS + i * FIFTEEN_MIN_MS) for i in range(4)]
    rows[0][1] = "42000.12345678"
    rows[0][5] = "1.23456789"
    mock_binance(rows)

    run(source, stores)

    bar = catalog.read_bars(BAR_TYPE)[0]
    assert str(bar.open) == "42000.12"
    # Nautilus rounds to nearest here rather than truncating (1.23456789 ->
    # 1.23457). Harmless for bar volume, which is market data. Position sizing
    # is a different matter and rounds DOWN explicitly -- see Step 11.
    assert str(bar.volume) == "1.23457"


# --- raw comes first ----------------------------------------------------


@respx.mock
def test_raw_is_written_before_the_catalog(
    source: BinanceSpotSource, stores: tuple[Catalog, RawStore]
) -> None:
    _, raw_store = stores
    mock_binance()
    result = run(source, stores)
    assert len(result.raw_paths) == 1
    assert raw_store.read(result.raw_paths[0])["payload"] == one_hour_rows()


@respx.mock
def test_dry_run_records_raw_but_writes_no_bars(
    source: BinanceSpotSource, stores: tuple[Catalog, RawStore]
) -> None:
    catalog, raw_store = stores
    mock_binance()

    result = run(source, stores, dry_run=True)

    assert result.bars_written == 4
    assert catalog.read_bars(BAR_TYPE) == []
    assert len(raw_store.list("binance", "klines")) == 1


# --- idempotency --------------------------------------------------------


@respx.mock
def test_reingesting_a_covered_window_is_a_no_op(
    source: BinanceSpotSource, stores: tuple[Catalog, RawStore]
) -> None:
    catalog, _ = stores
    mock_binance()
    run(source, stores)
    before = [bar.ts_event for bar in catalog.read_bars(BAR_TYPE)]

    respx.get(KLINES).mock(side_effect=AssertionError("should not fetch a covered window"))
    second = run(source, stores)

    assert second.skipped is True
    assert second.bars_written == 0
    assert [bar.ts_event for bar in catalog.read_bars(BAR_TYPE)] == before


@respx.mock
def test_force_refetches_a_covered_window(
    source: BinanceSpotSource, stores: tuple[Catalog, RawStore]
) -> None:
    mock_binance()
    run(source, stores)
    mock_binance()

    result = run(source, stores, force=True)

    assert result.skipped is False
    assert result.bars_written == 4


# --- failure modes ------------------------------------------------------


@respx.mock
def test_a_discipline_violation_aborts_the_run(
    source: BinanceSpotSource, stores: tuple[Catalog, RawStore]
) -> None:
    catalog, raw_store = stores
    # A row whose open time is off the 15m grid.
    rows = [kline(START_MS + 1234)]
    mock_binance(rows)

    with pytest.raises(TimestampDisciplineError):
        run(source, stores)

    assert catalog.read_bars(BAR_TYPE) == []
    # Raw survives: it is the evidence for why the run failed.
    assert len(raw_store.list("binance", "klines")) == 1


def test_rejects_an_inverted_window(
    source: BinanceSpotSource, stores: tuple[Catalog, RawStore]
) -> None:
    catalog, raw_store = stores
    with pytest.raises(IngestError, match="start must precede end"):
        ingest(
            source=source,
            catalog=catalog,
            raw_store=raw_store,
            symbol="BTCUSDT",
            venue="BINANCE",
            timeframe=Timeframe.M15,
            start=END,
            end=START,
        )


@respx.mock
def test_instrument_is_written_alongside_the_bars(
    source: BinanceSpotSource, stores: tuple[Catalog, RawStore]
) -> None:
    catalog, _ = stores
    mock_binance()
    run(source, stores)
    assert catalog.instrument_ids() == ["BTCUSDT.BINANCE"]


# --- date parsing -------------------------------------------------------


def test_parse_day_treats_naive_dates_as_utc() -> None:
    # A local-time window would ingest a different range on a different machine.
    assert parse_day("2023-01-01") == datetime(2023, 1, 1, tzinfo=UTC)


def test_parse_day_accepts_full_iso() -> None:
    assert parse_day("2023-01-01T06:30:00+00:00") == datetime(2023, 1, 1, 6, 30, tzinfo=UTC)


def test_parse_day_converts_an_offset_to_utc() -> None:
    assert parse_day("2023-01-01T05:30:00+05:30") == datetime(2023, 1, 1, tzinfo=UTC)


def test_parse_day_rejects_nonsense() -> None:
    with pytest.raises(IngestError, match="could not parse date"):
        parse_day("last tuesday")


# --- CLI ----------------------------------------------------------------


@respx.mock
def test_cli_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mock_binance()
    settings = Settings(
        _env_file=None,
        catalog_path=str(tmp_path / "catalog"),
        raw_path=str(tmp_path / "raw"),
    )

    exit_code = main(
        [
            "--exchange", "binance",
            "--symbol", "BTCUSDT",
            "--market", "spot",
            "--timeframe", "15m",
            "--start", "2024-01-01",
            "--end", "2024-01-01T01:00:00+00:00",
        ],
        settings=settings,
    )

    assert exit_code == 0
    assert "4 bars" in capsys.readouterr().out
    assert len(Catalog(str(tmp_path / "catalog")).read_bars(BAR_TYPE)) == 4


def test_cli_reports_a_failure_with_a_stable_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(_env_file=None, catalog_path=str(tmp_path / "c"), raw_path=str(tmp_path / "r"))
    exit_code = main(
        [
            "--exchange", "binance",
            "--symbol", "BTCUSDT",
            "--market", "spot",
            "--timeframe", "15m",
            "--start", "2025-01-01",
            "--end", "2024-01-01",
        ],
        settings=settings,
    )
    assert exit_code == 1
    assert "REQUEST_INVALID" in capsys.readouterr().err


def test_cli_rejects_an_unknown_exchange() -> None:
    with pytest.raises(SystemExit):
        main(["--exchange", "kraken", "--symbol", "X", "--market", "spot",
              "--timeframe", "15m", "--start", "2024-01-01", "--end", "2024-01-02"])


def test_bar_type_is_built_from_the_timeframe() -> None:
    bar_type = BarType.from_str(BAR_TYPE)
    assert str(bar_type) == BAR_TYPE


# --- incremental extension ----------------------------------------------
#
# Both tests below cover bugs found by running against the real API: the
# catalog rejects a write whose interval overlaps an existing file, so an
# extend must fetch *only* the gap, snapped to the bar grid at both ends.


def mock_range(start_ms: int, count: int) -> None:
    respx.get(EXCHANGE_INFO).mock(return_value=httpx.Response(200, json=EXCHANGE_INFO_BODY))
    respx.get(KLINES).mock(
        side_effect=[
            httpx.Response(200, json=[kline(start_ms + i * FIFTEEN_MIN_MS) for i in range(count)]),
            httpx.Response(200, json=[]),
        ]
    )


@respx.mock
def test_extending_forwards_fetches_only_the_new_range(
    source: BinanceSpotSource, stores: tuple[Catalog, RawStore]
) -> None:
    catalog, raw_store = stores
    mock_range(START_MS, 4)
    run(source, stores)

    # Now ask for two hours. Only the second hour is missing.
    mock_range(START_MS + 4 * FIFTEEN_MIN_MS, 4)
    result = ingest(
        source=source, catalog=catalog, raw_store=raw_store,
        symbol="BTCUSDT", venue="BINANCE", timeframe=Timeframe.M15,
        start=START, end=datetime(2024, 1, 1, 2, tzinfo=UTC),
    )

    assert result.bars_written == 4
    bars = catalog.read_bars(BAR_TYPE)
    assert len(bars) == 8
    assert len({bar.ts_event for bar in bars}) == 8


@respx.mock
def test_extending_backwards_does_not_overlap_existing_data(
    source: BinanceSpotSource, stores: tuple[Catalog, RawStore]
) -> None:
    catalog, raw_store = stores
    mock_range(START_MS, 4)
    run(source, stores)

    # Ask for the hour *before*. The gap ends one nanosecond short of the
    # stored data; without flooring the window end to the grid, this fetches
    # the bar that closes exactly where existing data starts and the catalog
    # refuses the write.
    earlier_ms = START_MS - 4 * FIFTEEN_MIN_MS
    mock_range(earlier_ms, 4)
    result = ingest(
        source=source, catalog=catalog, raw_store=raw_store,
        symbol="BTCUSDT", venue="BINANCE", timeframe=Timeframe.M15,
        start=datetime(2023, 12, 31, 23, tzinfo=UTC), end=END,
    )

    assert result.bars_written == 4
    bars = catalog.read_bars(BAR_TYPE)
    assert len(bars) == 8
    assert len({bar.ts_event for bar in bars}) == 8
    assert all(
        bars[i + 1].ts_event - bars[i].ts_event == Timeframe.M15.nanoseconds
        for i in range(len(bars) - 1)
    )


# --- quality runs automatically after every ingest ----------------------


@respx.mock
def test_ingest_writes_a_quality_report(
    source: BinanceSpotSource, stores: tuple[Catalog, RawStore], tmp_path: Path
) -> None:
    catalog, raw_store = stores
    mock_binance()

    result = ingest(
        source=source, catalog=catalog, raw_store=raw_store,
        symbol="BTCUSDT", venue="BINANCE", timeframe=Timeframe.M15,
        start=START, end=END, artifact_path=str(tmp_path / "artifacts"),
    )

    assert result.quality is not None
    assert result.quality.bar_count == 4
    assert result.quality.counts == {}
    assert result.quality_path is not None
    document = json.loads(Path(result.quality_path).read_text())
    assert document["bar_type"] == BAR_TYPE
    assert document["failed"] is False


@respx.mock
def test_quality_report_flags_a_gap_without_failing(
    source: BinanceSpotSource, stores: tuple[Catalog, RawStore], tmp_path: Path
) -> None:
    catalog, raw_store = stores
    # Rows 0, 1 and 3 -- row 2 is missing, so the stored series has a hole.
    rows = [kline(START_MS + i * FIFTEEN_MIN_MS) for i in (0, 1, 3)]
    mock_binance(rows)

    result = ingest(
        source=source, catalog=catalog, raw_store=raw_store,
        symbol="BTCUSDT", venue="BINANCE", timeframe=Timeframe.M15,
        start=START, end=END, artifact_path=str(tmp_path / "artifacts"),
    )

    assert result.quality is not None
    assert result.quality.counts == {"GAP": 1}
    assert result.quality.failed is False
    assert "GAP=1" in result.describe()


@respx.mock
def test_dry_run_skips_the_quality_report(
    source: BinanceSpotSource, stores: tuple[Catalog, RawStore], tmp_path: Path
) -> None:
    catalog, raw_store = stores
    mock_binance()
    result = ingest(
        source=source, catalog=catalog, raw_store=raw_store,
        symbol="BTCUSDT", venue="BINANCE", timeframe=Timeframe.M15,
        start=START, end=END, dry_run=True, artifact_path=str(tmp_path / "artifacts"),
    )
    assert result.quality_path is None
