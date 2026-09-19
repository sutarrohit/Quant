"""Automatic data provisioning (ADR-003).

The point of these tests is the *boundary*: what reaches the venue and what
does not. A backtest that silently re-downloads a window it already holds is
slow and rate-limited; a backtest that silently runs on a shorter window than
it asked for is wrong.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from engine.data.catalog import Catalog
from engine.data.provision import ensure_window, source_for
from engine.data.sources.binance import BinanceSpotSource
from engine.data.timeframes import Timeframe
from engine.errors import DataRangeUnavailable, SymbolUnknownAtVenue, VenueUnsupported
from engine.settings import Settings
from tests.conftest import make_settings
from tests.data.test_binance import EXCHANGE_INFO, EXCHANGE_INFO_BODY, KLINES, kline

FIFTEEN_MIN_MS = 900_000
START = datetime(2024, 1, 1, tzinfo=UTC)
END = datetime(2024, 1, 1, 1, tzinfo=UTC)
START_MS = int(START.timestamp() * 1000)
BAR_TYPE = "BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(
        catalog_path=str(tmp_path / "catalog"),
        raw_path=str(tmp_path / "raw"),
        log_level="ERROR",
    )


@pytest.fixture
def source() -> BinanceSpotSource:
    return BinanceSpotSource(client=httpx.Client(), min_interval_s=0.0, sleep=lambda _: None)


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


def provision(settings: Settings, source: BinanceSpotSource, **overrides: Any) -> Any:
    return ensure_window(
        bar_type=overrides.pop("bar_type", BAR_TYPE),
        start=overrides.pop("start", START),
        end=overrides.pop("end", END),
        settings=settings,
        source=source,
    )


# --- the headline: a cold catalog fills itself ---------------------------


@respx.mock
def test_a_missing_window_is_fetched(settings: Settings, source: BinanceSpotSource) -> None:
    mock_binance()

    result = provision(settings, source)

    assert result.fetched
    assert result.bars_written == 4
    assert Catalog.from_settings(settings).read_bars(BAR_TYPE)


@respx.mock
def test_a_held_window_never_touches_the_venue(
    settings: Settings, source: BinanceSpotSource
) -> None:
    mock_binance()
    provision(settings, source)
    respx.reset()

    # No routes are mocked now, so any request at all raises rather than
    # silently passing through. That is the assertion.
    result = provision(settings, source)

    assert not result.fetched
    assert result.bars_written == 0


# --- the window is what was asked for, or it is an error -----------------


@respx.mock
def test_a_window_the_venue_cannot_cover_is_refused(
    settings: Settings, source: BinanceSpotSource
) -> None:
    # The venue holds only the second half of the hour; the request wants all
    # of it. A symbol listed after the requested start looks exactly like this.
    # (One bar short is tolerated as a boundary artifact -- this is two.)
    mock_binance(rows=[kline(START_MS + i * FIFTEEN_MIN_MS) for i in range(2, 4)])

    with pytest.raises(DataRangeUnavailable) as caught:
        provision(settings, source)

    assert caught.value.code.value == "DATA_RANGE_UNAVAILABLE"
    assert caught.value.details is not None
    # The error names the date to retry from, so the fix is one edit away.
    assert "earliestAvailable" in caught.value.details


@respx.mock
def test_a_trailing_partial_bar_is_tolerated(
    settings: Settings, source: BinanceSpotSource
) -> None:
    # A window ending *now* cannot contain a bar that has not closed yet. One
    # interval short at the far end is the normal shape of a correct answer,
    # not a failure.
    mock_binance()

    result = provision(settings, source, end=END + Timeframe.M15.duration)

    assert result.fetched


# --- errors that are the caller's, named as such -------------------------


@respx.mock
def test_an_unlisted_symbol_is_named(settings: Settings, source: BinanceSpotSource) -> None:
    respx.get(EXCHANGE_INFO).mock(
        return_value=httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})
    )

    with pytest.raises(SymbolUnknownAtVenue) as caught:
        provision(settings, source, bar_type="NOTACOIN.BINANCE-15-MINUTE-LAST-EXTERNAL")

    assert caught.value.code.value == "SYMBOL_UNKNOWN_AT_VENUE"


def test_a_venue_with_no_source_is_named(settings: Settings) -> None:
    with pytest.raises(VenueUnsupported) as caught:
        source_for("KRAKEN", settings)

    # "no source for KRAKEN", never "no data for your symbol".
    assert "KRAKEN" in str(caught.value)


def test_an_unsupported_timeframe_is_refused(settings: Settings) -> None:
    from engine.data.timeframes import UnsupportedTimeframe

    with pytest.raises(UnsupportedTimeframe):
        ensure_window(
            bar_type="BTCUSDT.BINANCE-3-MINUTE-LAST-EXTERNAL",
            start=START,
            end=END,
            settings=settings,
        )
