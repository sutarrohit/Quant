from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx

from engine.data.sources import KlinePage, MarketDataSource
from engine.data.sources.binance import MAX_LIMIT, BinanceSpotSource
from engine.data.timeframes import Timeframe
from engine.errors import UpstreamError, UpstreamRateLimited, UpstreamResponseInvalid

BASE = "https://api.binance.com"
KLINES = f"{BASE}/api/v3/klines"
EXCHANGE_INFO = f"{BASE}/api/v3/exchangeInfo"

FIFTEEN_MIN_MS = 900_000
START = datetime(2024, 1, 1, tzinfo=UTC)


def kline(open_ms: int, price: str = "42000.00") -> list[Any]:
    """One row in Binance's documented klines shape."""
    return [
        open_ms,
        price,
        "42100.00",
        "41900.00",
        "42050.00",
        "1.50000000",
        open_ms + FIFTEEN_MIN_MS - 1,  # close time, one ms short of the close
        "63075.00",
        42,
        "0.75",
        "31537.50",
        "0",
    ]


def full_hour(start_ms: int) -> list[list[Any]]:
    """Four 15m rows -- exactly covers the one-hour window `pages()` requests,
    so the walk terminates after a single page."""
    return [kline(start_ms + i * FIFTEEN_MIN_MS) for i in range(4)]


EXCHANGE_INFO_BODY = {
    "symbols": [
        {
            "symbol": "BTCUSDT",
            "baseAsset": "BTC",
            "quoteAsset": "USDT",
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01000000"},
                {
                    "filterType": "LOT_SIZE",
                    "stepSize": "0.00001000",
                    "minQty": "0.00001000",
                    "maxQty": "9000.00000000",
                },
                {"filterType": "NOTIONAL", "minNotional": "10.00000000"},
            ],
        }
    ]
}


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def source(sleeps: list[float]) -> BinanceSpotSource:
    # No real sleeping, and no throttle floor, so tests stay fast. The delays
    # the fetcher *would* have taken are recorded in `sleeps`.
    return BinanceSpotSource(
        client=httpx.Client(),
        backoff_base_s=1.0,
        min_interval_s=0.0,
        sleep=sleeps.append,
    )


def test_satisfies_the_source_protocol(source: BinanceSpotSource) -> None:
    assert isinstance(source, MarketDataSource)
    assert source.name == "binance"


# --- exchangeInfo -------------------------------------------------------


@respx.mock
def test_fetch_instrument_parses_filters(source: BinanceSpotSource) -> None:
    respx.get(EXCHANGE_INFO).mock(return_value=httpx.Response(200, json=EXCHANGE_INFO_BODY))

    spec = source.fetch_instrument("BTCUSDT")

    assert spec.symbol == "BTCUSDT"
    assert spec.venue == "BINANCE"
    assert spec.base_currency == "BTC"
    assert spec.quote_currency == "USDT"
    assert spec.price_increment == Decimal("0.01000000")
    assert spec.size_increment == Decimal("0.00001000")
    assert spec.min_notional == Decimal("10.00000000")


@respx.mock
def test_instrument_values_are_decimal_not_float(source: BinanceSpotSource) -> None:
    respx.get(EXCHANGE_INFO).mock(return_value=httpx.Response(200, json=EXCHANGE_INFO_BODY))
    spec = source.fetch_instrument("BTCUSDT")
    for value in (spec.price_increment, spec.size_increment, spec.min_notional):
        assert isinstance(value, Decimal)


@respx.mock
def test_fees_are_zero_not_guessed(source: BinanceSpotSource) -> None:
    # Public exchangeInfo carries no fee tiers. Fees are a mandatory backtest
    # input (spec section 7.3); inferring one here would make it the number
    # every result is silently built on.
    respx.get(EXCHANGE_INFO).mock(return_value=httpx.Response(200, json=EXCHANGE_INFO_BODY))
    spec = source.fetch_instrument("BTCUSDT")
    assert spec.maker_fee == Decimal(0)
    assert spec.taker_fee == Decimal(0)


@respx.mock
def test_missing_filter_is_an_error(source: BinanceSpotSource) -> None:
    body = {"symbols": [{"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT", "filters": []}]}
    respx.get(EXCHANGE_INFO).mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(UpstreamResponseInvalid, match="PRICE_FILTER"):
        source.fetch_instrument("BTCUSDT")


@respx.mock
def test_unknown_symbol_is_an_error(source: BinanceSpotSource) -> None:
    respx.get(EXCHANGE_INFO).mock(return_value=httpx.Response(200, json={"symbols": []}))
    with pytest.raises(UpstreamResponseInvalid, match="no symbols"):
        source.fetch_instrument("NOPE")


# --- klines paging ------------------------------------------------------


def pages(source: BinanceSpotSource, hours: int = 1) -> list[KlinePage]:
    end = datetime.fromtimestamp(START.timestamp() + hours * 3600, tz=UTC)
    return list(source.fetch_klines("BTCUSDT", Timeframe.M15, START, end))


@respx.mock
def test_single_page(source: BinanceSpotSource) -> None:
    start_ms = int(START.timestamp() * 1000)
    rows = [kline(start_ms + i * FIFTEEN_MIN_MS) for i in range(4)]
    respx.get(KLINES).mock(return_value=httpx.Response(200, json=rows))

    result = pages(source)

    assert len(result) == 1
    assert result[0].rows == rows
    assert result[0].params["interval"] == "15m"
    assert result[0].params["limit"] == str(MAX_LIMIT)


@respx.mock
def test_rows_are_returned_untransformed(source: BinanceSpotSource) -> None:
    # This layer fetches faithfully. Open-to-close correction is Step 4's job.
    start_ms = int(START.timestamp() * 1000)
    rows = full_hour(start_ms)
    respx.get(KLINES).mock(return_value=httpx.Response(200, json=rows))
    assert pages(source)[0].rows[0][0] == start_ms
    # close time is one ms short of the true close; Step 4 corrects this
    assert pages(source)[0].rows[0][6] == start_ms + FIFTEEN_MIN_MS - 1


@respx.mock
def test_pages_forward_until_the_window_is_covered(source: BinanceSpotSource) -> None:
    start_ms = int(START.timestamp() * 1000)
    first = [kline(start_ms + i * FIFTEEN_MIN_MS) for i in range(4)]
    second = [kline(start_ms + (4 + i) * FIFTEEN_MIN_MS) for i in range(4)]
    respx.get(KLINES).mock(
        side_effect=[
            httpx.Response(200, json=first),
            httpx.Response(200, json=second),
            httpx.Response(200, json=[]),
        ]
    )

    result = pages(source, hours=3)

    assert [page.rows for page in result] == [first, second]


@respx.mock
def test_an_empty_page_ends_the_walk(source: BinanceSpotSource) -> None:
    route = respx.get(KLINES).mock(return_value=httpx.Response(200, json=[]))
    assert pages(source, hours=100) == []
    assert route.call_count == 1


@respx.mock
def test_a_stuck_cursor_raises_instead_of_spinning(source: BinanceSpotSource) -> None:
    # A server that keeps returning the same last row would otherwise loop
    # forever, burning the rate limit against nothing.
    start_ms = int(START.timestamp() * 1000)
    respx.get(KLINES).mock(return_value=httpx.Response(200, json=[kline(start_ms - FIFTEEN_MIN_MS)]))
    with pytest.raises(UpstreamResponseInvalid, match="did not advance"):
        pages(source, hours=3)


def test_rejects_naive_datetimes(source: BinanceSpotSource) -> None:
    with pytest.raises(UpstreamError, match="timezone-aware"):
        list(source.fetch_klines("BTCUSDT", Timeframe.M15, datetime(2024, 1, 1), datetime(2024, 1, 2)))


def test_rejects_an_inverted_window(source: BinanceSpotSource) -> None:
    end = datetime(2023, 1, 1, tzinfo=UTC)
    with pytest.raises(UpstreamError, match="start must precede end"):
        list(source.fetch_klines("BTCUSDT", Timeframe.M15, START, end))


@respx.mock
def test_non_list_klines_payload_is_an_error(source: BinanceSpotSource) -> None:
    respx.get(KLINES).mock(return_value=httpx.Response(200, json={"code": -1121}))
    with pytest.raises(UpstreamResponseInvalid, match="expected a list"):
        pages(source)


# --- retry and backoff --------------------------------------------------


@respx.mock
def test_retries_a_429_then_succeeds(source: BinanceSpotSource, sleeps: list[float]) -> None:
    start_ms = int(START.timestamp() * 1000)
    rows = full_hour(start_ms)
    respx.get(KLINES).mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "2"}),
            httpx.Response(200, json=rows),
        ]
    )

    result = pages(source)

    assert result[0].rows == rows
    assert sleeps == [2.0]  # Retry-After was honoured, not the default backoff


@respx.mock
def test_backoff_doubles_without_retry_after(source: BinanceSpotSource, sleeps: list[float]) -> None:
    start_ms = int(START.timestamp() * 1000)
    respx.get(KLINES).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(200, json=full_hour(start_ms)),
        ]
    )

    pages(source)

    assert sleeps == [1.0, 2.0, 4.0]


@respx.mock
def test_retries_a_418_ip_ban(source: BinanceSpotSource) -> None:
    start_ms = int(START.timestamp() * 1000)
    respx.get(KLINES).mock(
        side_effect=[httpx.Response(418), httpx.Response(200, json=full_hour(start_ms))]
    )
    assert len(pages(source)) == 1


@respx.mock
def test_gives_up_after_max_attempts(sleeps: list[float]) -> None:
    source = BinanceSpotSource(
        client=httpx.Client(), max_attempts=3, backoff_base_s=1.0, min_interval_s=0.0, sleep=sleeps.append
    )
    route = respx.get(KLINES).mock(return_value=httpx.Response(429))

    with pytest.raises(UpstreamRateLimited, match="after 3 attempts"):
        pages(source)

    assert route.call_count == 3


@respx.mock
def test_a_400_is_not_retried(source: BinanceSpotSource) -> None:
    # Retrying a request we malformed just burns quota against our own error.
    route = respx.get(KLINES).mock(return_value=httpx.Response(400, text="Invalid symbol."))
    with pytest.raises(UpstreamError, match="400"):
        pages(source)
    assert route.call_count == 1


@respx.mock
def test_a_transport_error_is_retried(source: BinanceSpotSource) -> None:
    start_ms = int(START.timestamp() * 1000)
    respx.get(KLINES).mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json=full_hour(start_ms))]
    )
    assert len(pages(source)) == 1


@respx.mock
def test_throttles_between_requests() -> None:
    recorded: list[float] = []
    source = BinanceSpotSource(
        client=httpx.Client(), min_interval_s=0.5, sleep=recorded.append
    )
    start_ms = int(START.timestamp() * 1000)
    respx.get(KLINES).mock(
        side_effect=[
            httpx.Response(200, json=[kline(start_ms)]),
            httpx.Response(200, json=[]),
        ]
    )

    list(source.fetch_klines("BTCUSDT", Timeframe.M15, START, datetime(2024, 1, 1, 2, tzinfo=UTC)))

    # First request is not delayed; the second waits out the floor.
    assert len(recorded) == 1
    assert 0 < recorded[0] <= 0.5
