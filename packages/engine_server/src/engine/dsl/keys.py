"""Series identity, derived purely from a condition.

Split out of ``indicators.py`` for one reason: spec section 5.3 requires the
interpreter to be unit-testable **without Nautilus**, and the interpreter has to
know which series a condition reads. Everything here is string and integer
arithmetic over the schema, so the interpreter can import it and stay pure while
``indicators.py`` keeps the Nautilus imports.

Both modules derive keys from here, so the strategy that *builds* a series and
the interpreter that *reads* it cannot disagree about its name.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.errors import UnknownIndicatorError
from engine.types.dsl import Operator

#: Indicators whose `period` configures the indicator itself.
PERIODIC = frozenset({"rsi", "sma", "ema", "atr"})

#: Indicators read straight off the bar, with no period of their own.
BAR_DERIVED = frozenset({"volume", "close"})

INDICATOR_NAMES = PERIODIC | BAR_DERIVED

#: Operators that compare a subject against the moving average of itself, and
#: therefore need a second series.
SMA_OPERATORS = frozenset({Operator.GREATER_THAN_SMA, Operator.LESS_THAN_SMA})


@dataclass(frozen=True, slots=True)
class SeriesRef:
    """A series a condition needs, named so it can be shared."""

    key: str
    name: str
    period: int | None


def series_key(name: str, period: int | None) -> str:
    """Stable identity for one series.

    Two conditions naming ``rsi`` with period 14 resolve to the same key and
    therefore share one instance rather than computing the same numbers twice.
    """
    return name if period is None else f"{name}:{period}"


def subject_ref(indicator: str, period: int | None) -> SeriesRef:
    """The series the condition is *about*."""
    if indicator not in INDICATOR_NAMES:
        raise UnknownIndicatorError(f"unknown indicator: {indicator!r}")
    # `volume` has no period of its own: on a `greaterThanSma` condition the
    # period is the averaging window, which belongs to the reference series.
    own_period = None if indicator in BAR_DERIVED else period
    return SeriesRef(series_key(indicator, own_period), indicator, own_period)


def reference_ref(indicator: str, period: int | None) -> SeriesRef:
    """The moving-average series a ``*Sma`` operator compares against."""
    if period is None:
        raise UnknownIndicatorError(f"{indicator} comparison against an SMA requires a period")
    name = f"{indicator}Sma"
    return SeriesRef(series_key(name, period), name, period)


def required_refs(
    indicator: str,
    operator: Operator,
    period: int | None,
    reference: tuple[str, int | None] | None = None,
) -> tuple[SeriesRef, ...]:
    """Every series a condition reads, subject first and reference last.

    Three shapes:

    * a plain threshold comparison needs only the subject;
    * ``greaterThanSma`` / ``lessThanSma`` also need the subject's own moving
      average;
    * a comparison against another series -- what makes a crossover
      expressible -- needs that series too.

    Resolved here rather than improvised by the interpreter, so the strategy
    that *builds* a series and the interpreter that *reads* it cannot disagree
    about its name.
    """
    subject = subject_ref(indicator, period)
    if reference is not None:
        return (subject, subject_ref(*reference))
    if operator in SMA_OPERATORS:
        return (subject, reference_ref(indicator, period))
    return (subject,)
