"""RSI against an independent implementation.

Phase 4 in miniature: rather than trusting that an indicator computes what its
name suggests, reimplement it and compare. This one caught a real problem --
Nautilus's RSI defaults to EXPONENTIAL smoothing, and every published RSI
strategy means Wilder's (docs/nautilus-api-notes.md D13).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from nautilus_trader.indicators import MovingAverageType, RelativeStrengthIndex

from engine.dsl.indicators import build_series

CATALOG = Path("catalog")
BAR_TYPE = "BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL"
PERIOD = 14


def wilder_rsi(closes: list[float], period: int) -> dict[int, float]:
    """Wilder's RSI, written from the definition.

    Average gain and loss start at zero and smooth in with ``alpha = 1/n``;
    they are *not* seeded with the first observation. Seeding gives a curve
    that differs early and converges later, so the comparison would be
    meaningless over the first few hundred bars.
    """
    values: dict[int, float] = {}
    average_gain = average_loss = 0.0
    alpha = 1.0 / period

    for index in range(1, len(closes)):
        change = closes[index] - closes[index - 1]
        average_gain += alpha * (max(change, 0.0) - average_gain)
        average_loss += alpha * (max(-change, 0.0) - average_loss)
        values[index] = (
            100.0
            if average_loss == 0
            else 100 - 100 / (1 + average_gain / average_loss)
        )
    return values


def test_the_registry_uses_wilder_smoothing() -> None:
    # The default is EXPONENTIAL, which differs by up to 34 points on real
    # data -- the difference between oversold and overbought.
    synthetic = [100 + (i % 7) * 3 - (i % 5) * 2 for i in range(30)]

    ours = build_series("rsi", PERIOD)
    wilder = RelativeStrengthIndex(PERIOD, ma_type=MovingAverageType.WILDER)
    default = RelativeStrengthIndex(PERIOD)

    for value in synthetic:
        wilder.update_raw(float(value))
        default.update_raw(float(value))

    assert wilder.value != default.value, "the two smoothings should differ"

    for value in synthetic:
        ours.handle_bar(_bar(float(value)))
    # The registry's series is scaled to 0..100 (D7) and Wilder-smoothed (D13).
    assert abs(ours.value - wilder.value * 100) < 1e-9


def test_rsi_is_reported_on_the_conventional_scale() -> None:
    series = build_series("rsi", PERIOD)
    for value in [100 + (i % 7) * 3 for i in range(60)]:
        series.handle_bar(_bar(float(value)))
    assert 0 <= series.value <= 100
    assert series.value > 1, "a 0..1 value would never cross a threshold like 30"


def _bar(close: float) -> object:
    from nautilus_trader.model import Bar, BarType, Price, Quantity

    _bar.counter = getattr(_bar, "counter", 0) + 1  # type: ignore[attr-defined]
    step = 900_000_000_000
    ts = step * (1000 + _bar.counter)  # type: ignore[attr-defined]
    return Bar(
        bar_type=BarType.from_str(BAR_TYPE),
        open=Price.from_str(f"{close:.2f}"),
        high=Price.from_str(f"{close + 1:.2f}"),
        low=Price.from_str(f"{close - 1:.2f}"),
        close=Price.from_str(f"{close:.2f}"),
        volume=Quantity.from_str("1.00000"),
        ts_event=ts,
        ts_init=ts,
    )


@pytest.mark.skipif(
    not (CATALOG / "data" / "bar" / BAR_TYPE).exists(), reason="needs the Phase 0 catalog"
)
def test_matches_an_independent_implementation_on_real_data() -> None:
    """The strongest check available: two implementations, one answer.

    The tolerance is float epsilon, not a modelling allowance. Both compute the
    same recurrence over the same inputs; they differ only in the order the
    hardware accumulates it, which lands around 1e-14 on values near 50. A
    difference larger than that would mean one of them is computing something
    else.
    """
    from engine.data.catalog import Catalog

    bars = Catalog("./catalog").read_bars(BAR_TYPE)[:2000]
    closes = [float(bar.close) for bar in bars]

    series = build_series("rsi", PERIOD)
    engine_values: list[float | None] = []
    for bar in bars:
        series.handle_bar(bar)
        engine_values.append(series.value if series.initialized else None)

    reference = wilder_rsi(closes, PERIOD)
    compared = [index for index in range(PERIOD, len(bars)) if engine_values[index] is not None]

    assert len(compared) > 1900
    worst = max(abs(engine_values[i] - reference[i]) for i in compared)  # type: ignore[operator]
    assert worst < 1e-9, f"engine and reference diverged by {worst}"
