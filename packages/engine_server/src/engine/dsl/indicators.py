"""Indicator registry (spec section 5.4).

**The only module in ``dsl/`` that imports Nautilus.** Schema, hashing,
interpreter and validator stay pure Python, which is what lets the interpreter
be unit-tested without an engine.

Adding an indicator means adding one entry to ``INDICATORS`` and one test. If it
ever requires touching the interpreter, the abstraction is wrong.

Everything resolves to a ``Series``: one number per bar, plus a warmup flag.
That uniformity is the point. ``volume`` is not a Nautilus indicator -- it is
read straight off the bar -- and without a common shape it would leak into the
interpreter as a special case, which is exactly what section 5.4 forbids.

Import paths follow deviation D1 in docs/nautilus-api-notes.md: indicators are
flat exports from ``nautilus_trader.indicators``, not per-indicator submodules.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from nautilus_trader.indicators import (
    AverageTrueRange,
    ExponentialMovingAverage,
    MovingAverageType,
    RelativeStrengthIndex,
    SimpleMovingAverage,
)
from nautilus_trader.model import Bar

from engine.dsl.keys import SeriesRef, required_refs
from engine.dsl.schema import Operator
from engine.errors import UnknownIndicatorError

# Operators valid on an indicator that produces a continuous series.
SERIES_OPERATORS = frozenset(
    {
        Operator.CROSSES_ABOVE,
        Operator.CROSSES_BELOW,
        Operator.GREATER_THAN,
        Operator.LESS_THAN,
    }
)

#: Nautilus reports RSI on 0..1. The DSL speaks the conventional 0..100.
RSI_SCALE = 100.0

# Volume is spiky rather than continuous, so crossings are not meaningful on it;
# comparison against its own moving average is. Widening either set is a
# deliberate act, not a default.
VOLUME_OPERATORS = frozenset(
    {
        Operator.GREATER_THAN,
        Operator.LESS_THAN,
        Operator.GREATER_THAN_SMA,
        Operator.LESS_THAN_SMA,
    }
)


class Series(Protocol):
    """One number per bar."""

    @property
    def initialized(self) -> bool:
        """False until enough bars have been seen for the value to mean anything."""
        ...

    @property
    def value(self) -> float:
        """Current value. Only meaningful once ``initialized``."""
        ...

    def handle_bar(self, bar: Bar) -> None: ...


class NautilusSeries:
    """Wraps a Nautilus indicator."""

    def __init__(self, indicator: object) -> None:
        self._indicator = indicator

    @property
    def initialized(self) -> bool:
        return bool(self._indicator.initialized)  # type: ignore[attr-defined]

    @property
    def value(self) -> float:
        return float(self._indicator.value)  # type: ignore[attr-defined]

    def handle_bar(self, bar: Bar) -> None:
        self._indicator.handle_bar(bar)  # type: ignore[attr-defined]


class ScaledSeries:
    """A Nautilus indicator rescaled to the units the DSL speaks.

    Nautilus reports RSI on 0..1. Every RSI reference in the world -- and every
    spec anyone will write -- uses 0..100, so `crossesAbove 30` against the raw
    value can never fire. It would produce zero trades, which is
    indistinguishable from a strategy that simply found no signals.

    The conversion belongs here because this module is where DSL vocabulary is
    mapped onto Nautilus, and nowhere else has to know.
    """

    def __init__(self, indicator: object, factor: float) -> None:
        self._indicator = indicator
        self._factor = factor

    @property
    def initialized(self) -> bool:
        return bool(self._indicator.initialized)  # type: ignore[attr-defined]

    @property
    def value(self) -> float:
        return float(self._indicator.value) * self._factor  # type: ignore[attr-defined]

    def handle_bar(self, bar: Bar) -> None:
        self._indicator.handle_bar(bar)  # type: ignore[attr-defined]


class CloseSeries:
    """The bar's closing price.

    Ready from the first bar: there is nothing to warm up.
    """

    def __init__(self) -> None:
        self._value = 0.0
        self._seen = False

    @property
    def initialized(self) -> bool:
        return self._seen

    @property
    def value(self) -> float:
        return self._value

    def handle_bar(self, bar: Bar) -> None:
        self._value = float(bar.close)
        self._seen = True


class VolumeSeries:
    """The bar's own volume.

    Ready from the first bar: there is nothing to warm up. ``float`` is correct
    here -- this feeds indicator math, not money (spec section 12).
    """

    def __init__(self) -> None:
        self._value = 0.0
        self._seen = False

    @property
    def initialized(self) -> bool:
        return self._seen

    @property
    def value(self) -> float:
        return self._value

    def handle_bar(self, bar: Bar) -> None:
        self._value = float(bar.volume)
        self._seen = True


class VolumeSmaSeries:
    """Moving average of volume, for ``greaterThanSma`` / ``lessThanSma``.

    A plain ``SimpleMovingAverage`` fed bars would average the *close*, so the
    volume is pushed in with ``update_raw``.
    """

    def __init__(self, period: int) -> None:
        self._sma = SimpleMovingAverage(period)

    @property
    def initialized(self) -> bool:
        return bool(self._sma.initialized)

    @property
    def value(self) -> float:
        return float(self._sma.value)

    def handle_bar(self, bar: Bar) -> None:
        self._sma.update_raw(float(bar.volume))


@dataclass(frozen=True, slots=True)
class IndicatorSpec:
    build: Callable[[int | None], Series]
    operators: frozenset[Operator]
    requires_period: bool
    warmup: Callable[[int | None], int]


def _wilder_rsi(period: int) -> object:
    """RSI with Wilder smoothing -- the one every published strategy means."""
    return RelativeStrengthIndex(period, ma_type=MovingAverageType.WILDER)


def _periodic(
    factory: Callable[[int], object],
    operators: frozenset[Operator] = SERIES_OPERATORS,
    *,
    scale: float = 1.0,
) -> IndicatorSpec:
    def build(period: int | None) -> Series:
        if period is None:
            raise UnknownIndicatorError("indicator requires a period")
        indicator = factory(period)
        if scale == 1.0:
            return NautilusSeries(indicator)
        return ScaledSeries(indicator, scale)

    def warmup(period: int | None) -> int:
        # Verified against 1.231.0: RSI, SMA, EMA and ATR all report
        # `initialized` after exactly `period` bars.
        return period if period is not None else 0

    return IndicatorSpec(build=build, operators=operators, requires_period=True, warmup=warmup)


#: Indicator names a spec may name. Keys are the DSL vocabulary.
INDICATORS: dict[str, IndicatorSpec] = {
    # Two corrections, both measured rather than assumed:
    #   - Nautilus reports RSI on 0..1; specs use the conventional 0..100 (D7).
    #   - its default smoothing is EXPONENTIAL, but "RSI" everywhere else means
    #     Wilder's. The two differ by up to 34 points on real data (D13).
    "rsi": _periodic(_wilder_rsi, scale=RSI_SCALE),
    "sma": _periodic(SimpleMovingAverage),
    "ema": _periodic(ExponentialMovingAverage),
    "atr": _periodic(AverageTrueRange),
    "close": IndicatorSpec(
        build=lambda period: CloseSeries(),
        # A price crosses a moving average; it is a continuous series.
        operators=SERIES_OPERATORS,
        requires_period=False,
        warmup=lambda period: 1,
    ),
    "volume": IndicatorSpec(
        build=lambda period: VolumeSeries(),
        operators=VOLUME_OPERATORS,
        requires_period=False,
        warmup=lambda period: 1,
    ),
}

#: Series a condition implies but a spec can never name directly. The schema's
#: discriminated union has no member for these, so they are unreachable from
#: user input by construction.
DERIVED: dict[str, IndicatorSpec] = {
    "volumeSma": IndicatorSpec(
        build=lambda period: VolumeSmaSeries(period if period is not None else 1),
        operators=frozenset(),
        requires_period=True,
        warmup=lambda period: period if period is not None else 0,
    ),
}


def _spec_for(name: str) -> IndicatorSpec:
    spec = INDICATORS.get(name) or DERIVED.get(name)
    if spec is None:
        # Unknown indicators raise. Returning a default would turn a broken
        # strategy into a silently inert one (spec section 13, pitfall 9).
        raise UnknownIndicatorError(f"unknown indicator: {name!r}")
    return spec


def build_series(name: str, period: int | None) -> Series:
    return _spec_for(name).build(period)


def warmup_bars(name: str, period: int | None) -> int:
    """Bars needed before this series' value means anything."""
    return _spec_for(name).warmup(period)


def supported_operators(name: str) -> frozenset[Operator]:
    """Operators legal for an indicator. Consumed by the validator in Step 9."""
    return _spec_for(name).operators


def build(ref: SeriesRef) -> Series:
    """Instantiate the series a ref names."""
    return build_series(ref.name, ref.period)


def required_series(
    indicator: str,
    operator: Operator,
    period: int | None,
    reference: tuple[str, int | None] | None = None,
) -> tuple[SeriesRef, ...]:
    """Re-exported from ``keys`` so callers have one import for the registry."""
    return required_refs(indicator, operator, period, reference)
