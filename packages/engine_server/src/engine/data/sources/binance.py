"""Binance spot public REST.

No API key: `/api/v3/klines` and `/api/v3/exchangeInfo` are public endpoints.

This module fetches and records. It does **not** convert to Nautilus ``Bar``
objects -- that is Step 4, and keeping the two apart is what makes the raw store
an audit trail rather than a cache of something already transformed.

Rate limits are respected rather than discovered: a floor between requests, and
backoff on 429/418/5xx honouring ``Retry-After`` when the server sends one.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
from nautilus_trader.model import Bar, BarType
from nautilus_trader.model.instruments import Instrument

from engine.data.instruments import SpotInstrumentSpec
from engine.data.sources import KlinePage
from engine.data.timeframes import NANOS_PER_MILLI, Timeframe
from engine.errors import EngineError, ErrorCode

logger = logging.getLogger(__name__)

BINANCE_SPOT_BASE_URL = "https://api.binance.com"

# Binance caps a klines page at 1000 rows.
MAX_LIMIT = 1000

# Column positions in a klines row. Binance documents these by index only.
OPEN_TIME = 0
OPEN = 1
HIGH = 2
LOW = 3
CLOSE = 4
VOLUME = 5
CLOSE_TIME = 6  # deliberately unused -- see `parse_klines`

# 418 is an IP ban following ignored 429s; 429 is the rate limit itself.
_RATE_LIMITED = frozenset({418, 429})

_INTERVALS: dict[Timeframe, str] = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.H1: "1h",
    Timeframe.H4: "4h",
    Timeframe.D1: "1d",
}
assert set(_INTERVALS) == set(Timeframe)


class UpstreamError(EngineError):
    code = ErrorCode.UPSTREAM_UNAVAILABLE
    http_status = 502


class UpstreamRateLimited(UpstreamError):
    code = ErrorCode.UPSTREAM_RATE_LIMITED
    http_status = 429


class UpstreamResponseInvalid(UpstreamError):
    code = ErrorCode.UPSTREAM_RESPONSE_INVALID
    http_status = 502


def _to_millis(moment: datetime) -> int:
    if moment.tzinfo is None:
        raise UpstreamError(f"timestamps must be timezone-aware, got {moment!r}")
    return int(moment.timestamp() * 1_000)


def _filter_value(filters: list[dict[str, Any]], filter_type: str, key: str) -> Decimal:
    for entry in filters:
        if entry.get("filterType") == filter_type:
            value = entry.get(key)
            if value is None:
                break
            # Decimal from the exchange's own string. Passing through float
            # here would bake a rounding error into every price this
            # instrument ever quotes.
            return Decimal(str(value))
    raise UpstreamResponseInvalid(f"exchangeInfo is missing {filter_type}.{key}")


class BinanceSpotSource:
    """Fetches spot klines and instrument metadata from Binance."""

    name = "binance"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        base_url: str = BINANCE_SPOT_BASE_URL,
        max_attempts: int = 5,
        backoff_base_s: float = 1.0,
        min_interval_s: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=30.0)
        self._max_attempts = max_attempts
        self._backoff_base_s = backoff_base_s
        self._min_interval_s = min_interval_s
        self._sleep = sleep
        self._last_request_at: float | None = None

    # --- HTTP ------------------------------------------------------------

    def _throttle(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._min_interval_s:
            self._sleep(self._min_interval_s - elapsed)

    def _backoff_seconds(self, attempt: int, response: httpx.Response | None) -> float:
        """Delay before the next attempt.

        Honours ``Retry-After`` when present, otherwise doubles. No jitter: an
        unseeded random would violate the determinism rule (spec section 12),
        and jitter buys nothing for a single-process batch ingest.
        """
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    return float(retry_after)
                except ValueError:
                    logger.warning("unparsable retry-after", extra={"value": retry_after})
        return float(self._backoff_base_s * (2**attempt))

    def _get(self, path: str, params: dict[str, str]) -> tuple[Any, dict[str, str]]:
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(self._max_attempts):
            self._throttle()
            try:
                response = self._client.get(url, params=params)
                self._last_request_at = time.monotonic()
            except httpx.RequestError as exc:
                last_error = exc
                logger.warning(
                    "request failed, retrying",
                    extra={"path": path, "attempt": attempt, "error": str(exc)},
                )
                self._sleep(self._backoff_seconds(attempt, None))
                continue

            if response.status_code in _RATE_LIMITED or response.status_code >= 500:
                last_error = UpstreamError(f"{response.status_code} from {path}")
                delay = self._backoff_seconds(attempt, response)
                logger.warning(
                    "upstream throttled or unavailable, retrying",
                    extra={
                        "path": path,
                        "attempt": attempt,
                        "status": response.status_code,
                        "delay_s": delay,
                        "used_weight_1m": response.headers.get("x-mbx-used-weight-1m"),
                    },
                )
                self._sleep(delay)
                continue

            if response.status_code >= 400:
                # A 4xx that is not a rate limit is a bad request; retrying it
                # just burns quota against an error we caused.
                raise UpstreamError(f"{response.status_code} from {path}: {response.text[:200]}")

            try:
                payload = response.json()
            except ValueError as exc:
                raise UpstreamResponseInvalid(f"non-JSON response from {path}") from exc
            return payload, dict(response.headers)

        message = f"giving up on {path} after {self._max_attempts} attempts: {last_error}"
        if isinstance(last_error, UpstreamError):
            raise UpstreamRateLimited(message)
        raise UpstreamError(message)

    # --- endpoints -------------------------------------------------------

    def fetch_instrument(self, symbol: str) -> SpotInstrumentSpec:
        payload, _ = self._get("/api/v3/exchangeInfo", {"symbol": symbol})
        symbols = payload.get("symbols") if isinstance(payload, dict) else None
        if not symbols:
            raise UpstreamResponseInvalid(f"exchangeInfo returned no symbols for {symbol}")

        entry = symbols[0]
        filters = entry.get("filters", [])
        return SpotInstrumentSpec(
            symbol=entry["symbol"],
            venue="BINANCE",
            base_currency=entry["baseAsset"],
            quote_currency=entry["quoteAsset"],
            price_increment=_filter_value(filters, "PRICE_FILTER", "tickSize"),
            size_increment=_filter_value(filters, "LOT_SIZE", "stepSize"),
            min_quantity=_filter_value(filters, "LOT_SIZE", "minQty"),
            max_quantity=_filter_value(filters, "LOT_SIZE", "maxQty"),
            min_notional=_filter_value(filters, "NOTIONAL", "minNotional"),
            # Public exchangeInfo does not carry fee tiers. Fees are a mandatory
            # request input at backtest time (spec section 7.3), never inferred
            # here -- a fee guessed at ingest would silently become the number
            # every result is built on.
            maker_fee=Decimal(0),
            taker_fee=Decimal(0),
        )

    def fetch_klines(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> Iterator[KlinePage]:
        """Page through ``[start, end)``, oldest first.

        Binance returns bar **open** times and pages forward from ``startTime``.
        Rows are yielded untouched; the open-to-close correction happens in
        Step 4, where there is a test that fails if it is removed.
        """
        start_ms = _to_millis(start)
        end_ms = _to_millis(end)
        if start_ms >= end_ms:
            raise UpstreamError(f"start must precede end, got {start} .. {end}")

        interval_ms = timeframe.milliseconds
        cursor = start_ms

        while cursor < end_ms:
            params = {
                "symbol": symbol,
                "interval": _INTERVALS[timeframe],
                "startTime": str(cursor),
                "endTime": str(end_ms - 1),
                "limit": str(MAX_LIMIT),
            }
            payload, headers = self._get("/api/v3/klines", params)
            if not isinstance(payload, list):
                raise UpstreamResponseInvalid(f"klines returned {type(payload).__name__}, expected a list")
            if not payload:
                return

            yield KlinePage(rows=payload, params=params, response_headers=headers)

            last_open_ms = int(payload[-1][0])
            next_cursor = last_open_ms + interval_ms
            if next_cursor <= cursor:
                # Defensive: a server that stops advancing would otherwise spin
                # this loop forever against the rate limit.
                raise UpstreamResponseInvalid(
                    f"klines cursor did not advance past {cursor}; last open was {last_open_ms}",
                )
            cursor = next_cursor

    def parse_klines(
        self,
        page: KlinePage,
        instrument: Instrument,
        bar_type: BarType,
        timeframe: Timeframe,
    ) -> list[Bar]:
        """Convert one page of rows into Nautilus bars.

        **The interval addition below is the whole point of this function.**
        Binance gives two timestamps and neither is the bar close:

        ==========  ==========================  ==============
        Field       15m bar opening 00:00:00Z   What it is
        ==========  ==========================  ==============
        ``[0]``     ``1704067200000``           open
        ``[6]``     ``1704068099999``           close minus 1ms
        ==========  ==========================  ==============

        ``ts_event`` must be the true close, ``open + interval``. Using ``[0]``
        puts every bar a whole interval early -- lookahead that no downstream
        test can detect. Using ``[6]`` puts it 1ms early, which silently breaks
        grid alignment. See docs/nautilus-api-notes.md D4.

        Prices and quantities are quantized by the *instrument*, so precision
        comes from exchange metadata rather than from however many decimals
        Binance happened to send.
        """
        interval_ns = timeframe.nanoseconds
        bars: list[Bar] = []

        for row in page.rows:
            # Binance returns the bar OPEN. The close is one interval later.
            ts_event = int(row[OPEN_TIME]) * NANOS_PER_MILLI + interval_ns
            bars.append(
                Bar(
                    bar_type=bar_type,
                    open=instrument.make_price(Decimal(str(row[OPEN]))),
                    high=instrument.make_price(Decimal(str(row[HIGH]))),
                    low=instrument.make_price(Decimal(str(row[LOW]))),
                    close=instrument.make_price(Decimal(str(row[CLOSE]))),
                    volume=instrument.make_qty(Decimal(str(row[VOLUME]))),
                    ts_event=ts_event,
                    # Historical ingest: the platform could first have known
                    # the bar at its close (spec section 4.2).
                    ts_init=ts_event,
                )
            )
        return bars

    def close(self) -> None:
        self._client.close()
