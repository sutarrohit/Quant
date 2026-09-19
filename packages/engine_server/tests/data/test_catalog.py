from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from nautilus_trader.model import Bar, BarType
from nautilus_trader.model.instruments import CurrencyPair

from engine.data.catalog import Catalog
from engine.errors import CatalogError
from engine.settings import Settings
from tests.data.conftest import FIFTEEN_MIN_NS, FIRST_CLOSE_NS

MakeBars = Callable[..., list[Bar]]


def test_round_trip_preserves_order_and_timestamps(
    catalog: Catalog, instrument: CurrencyPair, bar_type: BarType, make_bars: MakeBars
) -> None:
    # The Step 2 gate: 500 bars out must equal 500 bars in, exactly.
    written = make_bars(500)
    catalog.write_instruments([instrument])
    catalog.write_bars(written)

    read = catalog.read_bars(bar_type)

    assert len(read) == 500
    assert [bar.ts_event for bar in read] == [bar.ts_event for bar in written]
    assert all(read[i].ts_event < read[i + 1].ts_event for i in range(len(read) - 1))
    assert read[0].ts_event == FIRST_CLOSE_NS
    assert read[-1].ts_event == FIRST_CLOSE_NS + 499 * FIFTEEN_MIN_NS


def test_round_trip_preserves_prices_exactly(
    catalog: Catalog, bar_type: BarType, make_bars: MakeBars
) -> None:
    written = make_bars(50)
    catalog.write_bars(written)
    read = catalog.read_bars(bar_type)
    assert [(b.open, b.high, b.low, b.close, b.volume) for b in read] == [
        (b.open, b.high, b.low, b.close, b.volume) for b in written
    ]


def test_ts_init_equals_ts_event_for_historical_ingest(
    catalog: Catalog, bar_type: BarType, make_bars: MakeBars
) -> None:
    catalog.write_bars(make_bars(10))
    assert all(bar.ts_init == bar.ts_event for bar in catalog.read_bars(bar_type))


def test_write_rejects_ts_init_before_ts_event(catalog: Catalog, make_bars: MakeBars) -> None:
    # Spec section 4.2: a bar whose ts_init precedes its close is visible to a
    # strategy before it happened. Refuse the write rather than store it.
    with pytest.raises(CatalogError, match="ts_init precedes ts_event"):
        catalog.write_bars(make_bars(5, ts_init_offset=-1))


def test_write_rejects_the_whole_batch_not_just_the_bad_bar(
    catalog: Catalog, bar_type: BarType, make_bars: MakeBars
) -> None:
    bars = make_bars(5)
    bars[-1] = Bar(
        bar_type=bars[-1].bar_type,
        open=bars[-1].open,
        high=bars[-1].high,
        low=bars[-1].low,
        close=bars[-1].close,
        volume=bars[-1].volume,
        ts_event=bars[-1].ts_event,
        ts_init=bars[-1].ts_event - 1,
    )
    with pytest.raises(CatalogError):
        catalog.write_bars(bars)
    assert catalog.read_bars(bar_type) == []


def test_range_query_is_inclusive_at_both_ends(
    catalog: Catalog, bar_type: BarType, make_bars: MakeBars
) -> None:
    catalog.write_bars(make_bars(200))
    start = FIRST_CLOSE_NS + 100 * FIFTEEN_MIN_NS
    end = FIRST_CLOSE_NS + 149 * FIFTEEN_MIN_NS

    read = catalog.read_bars(bar_type, start=start, end=end)

    assert len(read) == 50
    assert read[0].ts_event == start
    assert read[-1].ts_event == end


def test_bar_types_are_isolated_from_each_other(
    catalog: Catalog, instrument: CurrencyPair, bar_type: BarType, make_bars: MakeBars
) -> None:
    hourly = BarType.from_str(f"{instrument.id}-1-HOUR-LAST-EXTERNAL")
    fifteen = make_bars(10)
    catalog.write_bars(fifteen)
    catalog.write_bars(
        [
            Bar(
                bar_type=hourly,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=b.volume,
                ts_event=b.ts_event,
                ts_init=b.ts_init,
            )
            for b in fifteen[:4]
        ]
    )

    assert len(catalog.read_bars(bar_type)) == 10
    assert len(catalog.read_bars(hourly)) == 4
    assert catalog.bar_types() == sorted([str(bar_type), str(hourly)])


def test_bar_types_are_sorted_for_determinism(catalog: Catalog) -> None:
    assert catalog.bar_types() == sorted(catalog.bar_types())


def test_instruments_round_trip(catalog: Catalog, instrument: CurrencyPair) -> None:
    catalog.write_instruments([instrument])
    read = catalog.instruments()
    assert len(read) == 1
    assert str(read[0].id) == "BTCUSDT.BINANCE"
    assert read[0].price_precision == instrument.price_precision
    assert read[0].size_precision == instrument.size_precision
    assert catalog.instrument_ids() == ["BTCUSDT.BINANCE"]


def test_coverage_reports_the_held_range(
    catalog: Catalog, bar_type: BarType, make_bars: MakeBars
) -> None:
    catalog.write_bars(make_bars(100))
    coverage = catalog.coverage(bar_type)

    assert coverage is not None
    assert coverage.start_ns == FIRST_CLOSE_NS
    assert coverage.end_ns == FIRST_CLOSE_NS + 99 * FIFTEEN_MIN_NS
    assert coverage.start.isoformat() == "2024-01-01T00:15:00+00:00"
    assert coverage.end.tzinfo is not None


def test_coverage_is_none_for_an_absent_bar_type(catalog: Catalog, bar_type: BarType) -> None:
    assert catalog.coverage(bar_type) is None


def test_reading_an_absent_bar_type_returns_empty(catalog: Catalog, bar_type: BarType) -> None:
    assert catalog.read_bars(bar_type) == []


def test_writing_nothing_is_a_no_op(catalog: Catalog) -> None:
    catalog.write_bars([])
    catalog.write_instruments([])
    assert catalog.bar_types() == []


def test_accepts_bar_type_as_string(
    catalog: Catalog, bar_type: BarType, make_bars: MakeBars
) -> None:
    catalog.write_bars(make_bars(3))
    assert len(catalog.read_bars(str(bar_type))) == 3


def test_exists_reflects_the_root(tmp_path: Path, make_bars: MakeBars) -> None:
    catalog = Catalog(str(tmp_path / "catalog"))
    assert catalog.exists() is False
    catalog.write_bars(make_bars(1))
    assert catalog.exists() is True


def test_from_settings_uses_the_catalog_path(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, catalog_path=str(tmp_path / "cat"))
    assert Catalog.from_settings(settings).root == str(tmp_path / "cat")


def test_relative_paths_resolve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # from_uri resolves a bare relative path against the cwd; a catalog that
    # silently pointed somewhere else would be very hard to notice.
    monkeypatch.chdir(tmp_path)
    catalog = Catalog("./catalog")
    (tmp_path / "catalog").mkdir()
    assert catalog.exists() is True
