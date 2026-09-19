from __future__ import annotations

from collections.abc import Callable

import pytest
from nautilus_trader.model import Bar, BarType, Price, Quantity

from engine.data.bars import check_bars
from engine.data.timeframes import Timeframe
from engine.errors import TimestampDisciplineError
from tests.data.conftest import FIFTEEN_MIN_NS, FIRST_CLOSE_NS

MakeBars = Callable[..., list[Bar]]

# The open of the bar that closes at FIRST_CLOSE_NS.
FIRST_OPEN_NS = FIRST_CLOSE_NS - FIFTEEN_MIN_NS


def retime(bar: Bar, *, ts_event: int, ts_init: int | None = None) -> Bar:
    return Bar(
        bar_type=bar.bar_type,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        ts_event=ts_event,
        ts_init=ts_event if ts_init is None else ts_init,
    )


def test_accepts_well_formed_bars(make_bars: MakeBars) -> None:
    check_bars(make_bars(50), Timeframe.M15, window_start_ns=FIRST_OPEN_NS)


def test_accepts_an_empty_batch() -> None:
    check_bars([], Timeframe.M15)


# --- the open-vs-close guard -------------------------------------------


def test_open_stamped_bars_are_rejected(make_bars: MakeBars) -> None:
    """The assertion that fails if the interval addition is ever removed.

    A parser that forgot to add the interval produces bars stamped with their
    open time -- exactly one interval early. Nothing downstream can detect
    that, so it has to be caught here.
    """
    open_stamped = [
        retime(bar, ts_event=bar.ts_event - FIFTEEN_MIN_NS) for bar in make_bars(10)
    ]
    with pytest.raises(TimestampDisciplineError, match="the interval was never added"):
        check_bars(open_stamped, Timeframe.M15, window_start_ns=FIRST_OPEN_NS)


def test_close_stamped_bars_pass_the_same_check(make_bars: MakeBars) -> None:
    # The mirror of the test above: correct bars must survive it.
    check_bars(make_bars(10), Timeframe.M15, window_start_ns=FIRST_OPEN_NS)


def test_window_check_is_skipped_when_no_window_given(make_bars: MakeBars) -> None:
    open_stamped = [retime(b, ts_event=b.ts_event - FIFTEEN_MIN_NS) for b in make_bars(3)]
    check_bars(open_stamped, Timeframe.M15)


# --- ts_init rules ------------------------------------------------------


def test_rejects_ts_init_before_ts_event(make_bars: MakeBars) -> None:
    bars = make_bars(3)
    bars[1] = retime(bars[1], ts_event=bars[1].ts_event, ts_init=bars[1].ts_event - 1)
    with pytest.raises(TimestampDisciplineError, match="cannot be known before it closed"):
        check_bars(bars, Timeframe.M15)


def test_rejects_ts_init_after_ts_event_for_historical(make_bars: MakeBars) -> None:
    # Spec section 4.2: historical ingest means ts_init == ts_event exactly.
    bars = make_bars(3)
    bars[2] = retime(bars[2], ts_event=bars[2].ts_event, ts_init=bars[2].ts_event + 1)
    with pytest.raises(TimestampDisciplineError, match="ts_init == ts_event"):
        check_bars(bars, Timeframe.M15)


# --- grid, ordering, sanity --------------------------------------------


def test_rejects_a_timestamp_off_the_grid(make_bars: MakeBars) -> None:
    bars = make_bars(3)
    bars[1] = retime(bars[1], ts_event=bars[1].ts_event + 1)
    with pytest.raises(TimestampDisciplineError, match="not aligned to the 15m grid"):
        check_bars(bars, Timeframe.M15)


def test_rejects_a_binance_close_time_off_by_one_ms(make_bars: MakeBars) -> None:
    # Binance field [6] is close-minus-1ms. Using it directly lands here.
    bars = [retime(bar, ts_event=bar.ts_event - 1_000_000) for bar in make_bars(3)]
    with pytest.raises(TimestampDisciplineError, match="not aligned"):
        check_bars(bars, Timeframe.M15)


def test_rejects_duplicate_timestamps(make_bars: MakeBars) -> None:
    bars = make_bars(3)
    bars[2] = retime(bars[2], ts_event=bars[1].ts_event)
    with pytest.raises(TimestampDisciplineError, match="duplicate ts_event"):
        check_bars(bars, Timeframe.M15)


def test_rejects_out_of_order_timestamps(make_bars: MakeBars) -> None:
    bars = make_bars(5)
    bars[1], bars[3] = bars[3], bars[1]
    with pytest.raises(TimestampDisciplineError, match="goes backwards"):
        check_bars(bars, Timeframe.M15)


def test_gaps_are_allowed_here(make_bars: MakeBars) -> None:
    # Spec section 4.3: ingestion fails on duplicates and non-monotonicity but
    # only *warns* on gaps. Reporting them is Step 5's job.
    bars = make_bars(5)
    del bars[2]
    check_bars(bars, Timeframe.M15)


def test_rejects_a_non_positive_timestamp(make_bars: MakeBars) -> None:
    bars = make_bars(1)
    with pytest.raises(TimestampDisciplineError, match="must be positive"):
        check_bars([retime(bars[0], ts_event=0)], Timeframe.M15)


def test_error_names_the_offending_bar(make_bars: MakeBars) -> None:
    bars = make_bars(5)
    bars[3] = retime(bars[3], ts_event=bars[3].ts_event + 1)
    with pytest.raises(TimestampDisciplineError, match=r"bar 3 of BTCUSDT\.BINANCE"):
        check_bars(bars, Timeframe.M15)


@pytest.mark.parametrize("timeframe", list(Timeframe))
def test_grid_alignment_is_per_timeframe(timeframe: Timeframe) -> None:
    bar_type = BarType.from_str(f"BTCUSDT.BINANCE-{timeframe.aggregation}-LAST-EXTERNAL")
    interval = timeframe.nanoseconds
    aligned = [
        Bar(
            bar_type=bar_type,
            open=Price.from_str("1.00"),
            high=Price.from_str("2.00"),
            low=Price.from_str("0.50"),
            close=Price.from_str("1.50"),
            volume=Quantity.from_str("1.00000"),
            ts_event=interval * (100 + i),
            ts_init=interval * (100 + i),
        )
        for i in range(3)
    ]
    check_bars(aligned, timeframe)

    misaligned = [retime(aligned[0], ts_event=aligned[0].ts_event + 1)]
    with pytest.raises(TimestampDisciplineError, match="not aligned"):
        check_bars(misaligned, timeframe)
