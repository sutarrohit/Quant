"""Scaffold smoke test for the engine project (D-02).

Exercises the `synthetic_bars` fixture only — no engine package is imported here, proving
`engine/tests/dsl` is runnable in an environment where the trading engine is not installed.
"""

import decimal


def test_synthetic_bars_length(synthetic_bars):
    assert len(synthetic_bars) >= 40


def test_synthetic_bars_ts_event_strictly_increasing(synthetic_bars):
    timestamps = [bar.ts_event for bar in synthetic_bars]
    assert timestamps == sorted(timestamps)
    assert len(timestamps) == len(set(timestamps))


def test_synthetic_bars_prices_are_decimal_strings(synthetic_bars):
    for bar in synthetic_bars:
        for field in ("open", "high", "low", "close", "volume"):
            value = getattr(bar, field)
            assert isinstance(value, str)
            # Must parse cleanly as Decimal without ever having gone through float.
            decimal.Decimal(value)
