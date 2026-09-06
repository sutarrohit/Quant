"""Shared fixtures for engine unit tests (D-02).

`synthetic_bars` is independent of any ingested data and of the trading engine: it imports
nothing outside the standard library, so `engine/tests/dsl` can run even where Nautilus is not
installed.
"""

import dataclasses
import decimal
import math

import pytest

_BAR_COUNT = 48
_ONE_HOUR_NS = 60 * 60 * 1_000_000_000
_START_TS_EVENT_NS = 1_700_000_000 * 1_000_000_000  # arbitrary fixed epoch, nanoseconds


@dataclasses.dataclass(frozen=True)
class SyntheticBar:
    open: str
    high: str
    low: str
    close: str
    volume: str
    ts_event: int


def _generate_bars() -> list[SyntheticBar]:
    """Deterministic sine-wave close series.

    A 16-bar period sine wave over 48 bars crosses a 5-period and a 20-period SMA at least
    once in each direction (verified: downward cross at bar 27, upward at bar 35, downward at
    bar 43), while every OHLC field stays a fixed-precision decimal string never touched by
    `float` arithmetic downstream — the wave shape is computed once, then quantized to strings.
    """
    closes = [
        decimal.Decimal(str(round(100 + 10 * math.sin(2 * math.pi * i / 16), 2))) for i in range(_BAR_COUNT)
    ]

    bars: list[SyntheticBar] = []
    prior_close = closes[0]
    for i, close in enumerate(closes):
        open_ = prior_close
        high = max(open_, close) + decimal.Decimal("0.50")
        low = min(open_, close) - decimal.Decimal("0.50")
        volume = decimal.Decimal("10.0")
        ts_event = _START_TS_EVENT_NS + i * _ONE_HOUR_NS
        bars.append(
            SyntheticBar(
                open=str(open_),
                high=str(high),
                low=str(low),
                close=str(close),
                volume=str(volume),
                ts_event=ts_event,
            )
        )
        prior_close = close
    return bars


@pytest.fixture
def synthetic_bars() -> list[SyntheticBar]:
    return _generate_bars()
