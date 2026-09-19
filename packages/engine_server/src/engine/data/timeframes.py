"""The closed set of supported bar intervals.

Spec section 5.1 makes ``timeframe`` a closed enum. It lives here rather than in
``dsl/schema.py`` because ingest needs it two phases before the DSL exists, and
two definitions of "what is a 15m bar" would eventually disagree.

Adding a timeframe is deliberate: add the member, its duration, and its Nautilus
aggregation spec, all in this file.
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum

from nautilus_trader.model import BarType

from engine.errors import EngineError, ErrorCode

NANOS_PER_MILLI = 1_000_000


class Timeframe(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"

    @property
    def duration(self) -> timedelta:
        return _DURATIONS[self]

    @property
    def milliseconds(self) -> int:
        """Interval in ms -- the unit Binance's REST API speaks."""
        return int(self.duration.total_seconds() * 1_000)

    @property
    def nanoseconds(self) -> int:
        """Interval in ns -- the unit Nautilus timestamps use."""
        return self.milliseconds * NANOS_PER_MILLI

    @property
    def aggregation(self) -> str:
        """The step and aggregation half of a Nautilus ``BarType`` string.

        ``Timeframe.M15.aggregation`` is ``"15-MINUTE"``, which combines into
        ``"BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL"``.
        """
        return _AGGREGATIONS[self]

    @classmethod
    def from_bar_type(cls, bar_type: BarType | str) -> Timeframe:
        """The timeframe a Nautilus ``BarType`` names.

        The inverse of :attr:`aggregation`, and derived from the same table so
        the two cannot drift. A bar type outside the closed set is refused
        rather than approximated: an unsupported interval reaching ingest would
        produce bars nothing else in the system can read.
        """
        spec = str(bar_type).split("-")
        if len(spec) < 3:
            raise UnsupportedTimeframe(f"{bar_type} is not a bar type this service understands")
        aggregation = f"{spec[1]}-{spec[2]}"
        for timeframe, candidate in _AGGREGATIONS.items():
            if candidate == aggregation:
                return timeframe
        raise UnsupportedTimeframe(
            f"{aggregation} is not a supported timeframe; supported: {', '.join(tf.value for tf in cls)}"
        )


class UnsupportedTimeframe(EngineError):
    """A bar type naming an interval outside the closed set."""

    code = ErrorCode.REQUEST_INVALID
    http_status = 422


_DURATIONS: dict[Timeframe, timedelta] = {
    Timeframe.M1: timedelta(minutes=1),
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.H1: timedelta(hours=1),
    Timeframe.H4: timedelta(hours=4),
    Timeframe.D1: timedelta(days=1),
}

_AGGREGATIONS: dict[Timeframe, str] = {
    Timeframe.M1: "1-MINUTE",
    Timeframe.M5: "5-MINUTE",
    Timeframe.M15: "15-MINUTE",
    Timeframe.H1: "1-HOUR",
    Timeframe.H4: "4-HOUR",
    Timeframe.D1: "1-DAY",
}

# A member without a duration or an aggregation would fail far from here.
assert set(_DURATIONS) == set(Timeframe)
assert set(_AGGREGATIONS) == set(Timeframe)
