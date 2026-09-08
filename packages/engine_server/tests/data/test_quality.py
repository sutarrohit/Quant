from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.model import Bar, Price, Quantity

from engine.data.quality import (
    OUTLIER_WINDOW,
    Finding,
    Severity,
    check_quality,
    write_report,
)
from engine.data.timeframes import Timeframe
from tests.data.conftest import FIFTEEN_MIN_NS

MakeBars = Callable[..., list[Bar]]


def rebuild(
    bar: Bar,
    *,
    ts_event: int | None = None,
    ohlc: tuple[str, str, str, str] | None = None,
    volume: str | None = None,
) -> Bar:
    """Rebuild a bar, optionally replacing its OHLC as one consistent set.

    Nautilus enforces low <= open/close <= high, so high and low cannot be
    changed in isolation -- a helper that let them drift apart would produce
    bars the engine would never accept anyway.
    """
    ts = bar.ts_event if ts_event is None else ts_event
    if ohlc is None:
        prices = (bar.open, bar.high, bar.low, bar.close)
    else:
        prices = tuple(Price.from_str(value) for value in ohlc)  # type: ignore[assignment]
    return Bar(
        bar_type=bar.bar_type,
        open=prices[0],
        high=prices[1],
        low=prices[2],
        close=prices[3],
        volume=bar.volume if volume is None else Quantity.from_str(volume),
        ts_event=ts,
        ts_init=ts,
    )


def codes(report: object) -> set[str]:
    return set(report.counts)  # type: ignore[attr-defined]


# --- clean data ---------------------------------------------------------


def test_clean_series_has_no_findings(make_bars: MakeBars) -> None:
    report = check_quality(make_bars(200), Timeframe.M15)
    assert report.counts == {}
    assert report.findings == []
    assert report.failed is False
    assert "clean" in report.describe()


def test_empty_series_is_handled(make_bars: MakeBars) -> None:
    report = check_quality([], Timeframe.M15)
    assert report.bar_count == 0
    assert report.start_ns is None
    assert report.failed is False


def test_report_carries_the_range(make_bars: MakeBars) -> None:
    bars = make_bars(50)
    report = check_quality(bars, Timeframe.M15)
    assert report.bar_count == 50
    assert report.start_ns == bars[0].ts_event
    assert report.end_ns == bars[-1].ts_event
    assert report.timeframe == "15m"


# --- the three corrupted fixtures the Phase 0 gate requires -------------


def test_duplicate_row_is_caught(make_bars: MakeBars) -> None:
    bars = make_bars(20)
    bars.insert(10, bars[10])

    report = check_quality(bars, Timeframe.M15)

    assert Finding.DUPLICATE_TIMESTAMP.value in report.counts
    assert report.failed is True
    assert report.failures[0].severity is Severity.FAIL


def test_out_of_order_row_is_caught(make_bars: MakeBars) -> None:
    bars = make_bars(20)
    bars[5], bars[15] = bars[15], bars[5]

    report = check_quality(bars, Timeframe.M15)

    assert Finding.NON_MONOTONIC.value in report.counts
    assert report.failed is True


def test_missing_day_is_caught(make_bars: MakeBars) -> None:
    # 96 bars is one day of 15m data.
    bars = make_bars(300)
    del bars[100:196]

    report = check_quality(bars, Timeframe.M15)

    assert report.counts[Finding.GAP.value] == 1
    gap = next(f for f in report.findings if f.code is Finding.GAP)
    assert gap.detail["missing_bars"] == 96
    # A gap is a fact about the market, not a contradiction. Warn, do not fail.
    assert gap.severity is Severity.WARN
    assert report.failed is False


# --- warnings -----------------------------------------------------------


def test_single_gap_reports_the_missing_count(make_bars: MakeBars) -> None:
    bars = make_bars(20)
    del bars[10]
    report = check_quality(bars, Timeframe.M15)
    assert report.counts[Finding.GAP.value] == 1
    assert report.findings[0].detail["missing_bars"] == 1
    assert report.findings[0].detail["resumes_at"] == bars[10].ts_event


def test_zero_range_bar_is_flagged(make_bars: MakeBars) -> None:
    bars = make_bars(10)
    bars[3] = rebuild(bars[3], ohlc=("42000.00", "42000.00", "42000.00", "42000.00"))
    report = check_quality(bars, Timeframe.M15)
    assert report.counts[Finding.ZERO_RANGE.value] == 1
    assert report.failed is False


def test_zero_volume_bar_is_flagged(make_bars: MakeBars) -> None:
    bars = make_bars(10)
    bars[7] = rebuild(bars[7], volume="0.00000")
    report = check_quality(bars, Timeframe.M15)
    assert report.counts[Finding.ZERO_VOLUME.value] == 1
    assert report.failed is False


def test_outlier_needs_a_full_trailing_window(make_bars: MakeBars) -> None:
    # With fewer than OUTLIER_WINDOW prior bars there is no baseline, so an
    # early spike must not be flagged on a guess.
    bars = make_bars(20)
    bars[10] = rebuild(bars[10], ohlc=("50000.00", "99000.00", "1000.00", "50000.00"))
    assert Finding.OUTLIER_RANGE.value not in check_quality(bars, Timeframe.M15).counts


def test_outlier_is_flagged_once_the_window_fills(make_bars: MakeBars) -> None:
    bars = make_bars(OUTLIER_WINDOW + 50)
    spike = OUTLIER_WINDOW + 10
    bars[spike] = rebuild(bars[spike], ohlc=("50000.00", "99000.00", "1000.00", "50000.00"))

    report = check_quality(bars, Timeframe.M15)

    assert report.counts[Finding.OUTLIER_RANGE.value] == 1
    finding = next(f for f in report.findings if f.code is Finding.OUTLIER_RANGE)
    assert finding.ts_event == bars[spike].ts_event
    # A flash crash is real history. Report it; do not refuse the ingest.
    assert report.failed is False


def test_outlier_multiple_is_tunable(make_bars: MakeBars) -> None:
    bars = make_bars(OUTLIER_WINDOW + 20)
    spike = OUTLIER_WINDOW + 5
    # 100 wide, against the fixture's usual 20
    bars[spike] = rebuild(bars[spike], ohlc=("42000.00", "42100.00", "42000.00", "42050.00"))

    assert Finding.OUTLIER_RANGE.value not in check_quality(bars, Timeframe.M15).counts
    strict = check_quality(bars, Timeframe.M15, outlier_multiple=Decimal("2"))
    assert strict.counts[Finding.OUTLIER_RANGE.value] == 1


# --- report shape -------------------------------------------------------


def test_findings_are_capped_but_counts_are_not(make_bars: MakeBars) -> None:
    bars = make_bars(400)
    for index in range(1, 300, 2):
        bars[index] = rebuild(bars[index], volume="0.00000")

    report = check_quality(bars, Timeframe.M15)

    assert report.counts[Finding.ZERO_VOLUME.value] == 150
    assert len([f for f in report.findings if f.code is Finding.ZERO_VOLUME]) == 50


def test_report_is_deterministic(make_bars: MakeBars) -> None:
    # Byte-identical output for identical input is what makes a stored report
    # worth comparing against a later one.
    bars = make_bars(200)
    del bars[50]
    bars[80] = rebuild(bars[80], volume="0.00000")

    first = json.dumps(check_quality(bars, Timeframe.M15).to_document(), sort_keys=True)
    second = json.dumps(check_quality(bars, Timeframe.M15).to_document(), sort_keys=True)
    assert first == second


def test_report_has_no_clock(make_bars: MakeBars) -> None:
    document = check_quality(make_bars(10), Timeframe.M15).to_document()
    assert "generated_at" not in document


def test_write_report_round_trips(tmp_path: Path, make_bars: MakeBars) -> None:
    bars = make_bars(20)
    del bars[10]
    report = check_quality(bars, Timeframe.M15)

    path = write_report(report, str(tmp_path / "artifacts"))

    document = json.loads(Path(path).read_text())
    assert document["bar_type"] == report.bar_type
    assert document["counts"] == report.counts
    assert document["failed"] is False
    assert "generated_at" in document  # added by the writer, not the report
    assert len(document["findings"]) == 1


def test_written_report_is_canonical_json(tmp_path: Path, make_bars: MakeBars) -> None:
    report = check_quality(make_bars(10), Timeframe.M15)
    text = Path(write_report(report, str(tmp_path / "a"))).read_text()
    assert text == json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))


@pytest.mark.parametrize(
    ("finding", "severity"),
    [
        (Finding.DUPLICATE_TIMESTAMP, Severity.FAIL),
        (Finding.NON_MONOTONIC, Severity.FAIL),
        (Finding.GAP, Severity.WARN),
        (Finding.OUTLIER_RANGE, Severity.WARN),
        (Finding.ZERO_VOLUME, Severity.WARN),
        (Finding.ZERO_RANGE, Severity.WARN),
    ],
)
def test_severity_split_matches_the_spec(finding: Finding, severity: Severity) -> None:
    # Spec section 4.3: fail on duplicates and non-monotonicity, warn on the
    # rest. Flipping one of these silently changes what ingestion accepts.
    report_finding = type("F", (), {"code": finding})()
    from engine.data.quality import _SEVERITIES

    assert _SEVERITIES[report_finding.code] is severity


def test_gap_at_the_very_end_of_a_series(make_bars: MakeBars) -> None:
    bars = make_bars(10)
    bars[-1] = rebuild(bars[-1], ts_event=bars[-1].ts_event + 10 * FIFTEEN_MIN_NS)
    report = check_quality(bars, Timeframe.M15)
    assert report.counts[Finding.GAP.value] == 1
