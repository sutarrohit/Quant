"""Timestamp discipline for ingested bars.

Spec section 4.2. This is where backtests silently become wrong, so the checks
here **abort ingestion** rather than warn -- a bar with a bad timestamp is worse
than a missing bar, because nothing downstream can tell it is wrong.

The rules, and what each one prevents:

``ts_event`` is the bar **close**
    Exchange APIs return the open. A bar stamped with its open time is visible
    to a strategy one whole interval before it finished forming, which is
    lookahead that no later test can detect. See ``check_bars``'s
    ``window_start_ns`` argument -- that is the check which catches a dropped
    interval addition.

``ts_init == ts_event``
    ``ts_init`` is when the platform could first have known the bar. For
    historical ingest that is the close, exactly.

``ts_init >= ts_event``, always
    A bar known *before* it closed is a time machine.

Grid alignment and strict monotonicity
    Spec section 4.3: ingestion fails on duplicate or non-monotonic timestamps.
    Gaps and outliers are Step 5's business -- those are reported, not refused.
"""

from __future__ import annotations

from collections.abc import Sequence

from nautilus_trader.model import Bar

from engine.data.timeframes import Timeframe
from engine.errors import EngineError, ErrorCode


class TimestampDisciplineError(EngineError):
    code = ErrorCode.TIMESTAMP_DISCIPLINE
    http_status = 422


def check_bars(
    bars: Sequence[Bar],
    timeframe: Timeframe,
    *,
    window_start_ns: int | None = None,
) -> None:
    """Raise ``TimestampDisciplineError`` on the first violation.

    ``window_start_ns`` is the start of the requested ingest window. When given,
    the first bar must close at or after ``window_start_ns + one interval``.
    That is the assertion which fails if the open-to-close correction is ever
    removed from a source's parser: an open-stamped bar lands exactly one
    interval early.
    """
    if not bars:
        return

    interval_ns = timeframe.nanoseconds
    previous_ts: int | None = None

    for index, bar in enumerate(bars):
        where = f"bar {index} of {bar.bar_type}"

        if not isinstance(bar.ts_event, int) or not isinstance(bar.ts_init, int):
            raise TimestampDisciplineError(f"{where}: timestamps must be integer nanoseconds")

        if bar.ts_event <= 0:
            raise TimestampDisciplineError(f"{where}: ts_event must be positive, got {bar.ts_event}")

        if bar.ts_init < bar.ts_event:
            raise TimestampDisciplineError(
                f"{where}: ts_init precedes ts_event ({bar.ts_init} < {bar.ts_event}); "
                "a bar cannot be known before it closed",
            )

        if bar.ts_init != bar.ts_event:
            raise TimestampDisciplineError(
                f"{where}: historical ingest requires ts_init == ts_event, "
                f"got ts_init={bar.ts_init} ts_event={bar.ts_event}",
            )

        if bar.ts_event % interval_ns != 0:
            raise TimestampDisciplineError(
                f"{where}: ts_event {bar.ts_event} is not aligned to the "
                f"{timeframe.value} grid ({interval_ns} ns)",
            )

        if previous_ts is not None:
            if bar.ts_event == previous_ts:
                raise TimestampDisciplineError(f"{where}: duplicate ts_event {bar.ts_event}")
            if bar.ts_event < previous_ts:
                raise TimestampDisciplineError(
                    f"{where}: ts_event {bar.ts_event} goes backwards from {previous_ts}",
                )
        previous_ts = bar.ts_event

    if window_start_ns is not None:
        earliest_close = window_start_ns + interval_ns
        first = bars[0]
        if first.ts_event < earliest_close:
            raise TimestampDisciplineError(
                f"first bar of {first.bar_type} closes at {first.ts_event}, before the earliest "
                f"possible close {earliest_close} for a window starting at {window_start_ns}. "
                "This is what an open-stamped bar looks like: the interval was never added.",
            )
