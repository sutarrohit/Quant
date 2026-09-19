"""Data quality monitors (spec section 4.3).

Run after every ingest. The split between failing and warning is the whole
design, and it is not arbitrary:

**Failures** are contradictions -- the data says two different things about one
moment in time. A duplicate or backwards timestamp means the series cannot be
trusted at all, so ingestion stops.

**Warnings** are facts about the market. A gap may be an exchange outage. An
outlier may be a flash crash. A zero-volume bar may be a quiet Sunday. Refusing
these would delete genuine history and leave a catalog that looks clean because
the interesting parts were dropped.

Reports are pure functions of the bars: no clock, no randomness, no dict
ordering. The same series always produces a byte-identical report, which is
what makes a stored report worth comparing against a later one.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

import fsspec
from nautilus_trader.model import Bar

from engine.data.timeframes import Timeframe

# Trailing window for the outlier baseline. Long enough to be a stable median,
# short enough to track a changing volatility regime.
OUTLIER_WINDOW = 100

# A bar whose range exceeds this multiple of the trailing median is flagged.
# Generous on purpose: this reports, it does not refuse, and a real crash must
# not be mistaken for corruption.
DEFAULT_OUTLIER_MULTIPLE = Decimal("10")

# Findings are capped per code so one broken day cannot produce a report larger
# than the data. Full totals always live in `counts`.
MAX_FINDINGS_PER_CODE = 50


class Severity(StrEnum):
    FAIL = "FAIL"
    WARN = "WARN"


class Finding(StrEnum):
    DUPLICATE_TIMESTAMP = "DUPLICATE_TIMESTAMP"
    NON_MONOTONIC = "NON_MONOTONIC"
    GAP = "GAP"
    OUTLIER_RANGE = "OUTLIER_RANGE"
    ZERO_VOLUME = "ZERO_VOLUME"
    ZERO_RANGE = "ZERO_RANGE"


_SEVERITIES: dict[Finding, Severity] = {
    Finding.DUPLICATE_TIMESTAMP: Severity.FAIL,
    Finding.NON_MONOTONIC: Severity.FAIL,
    Finding.GAP: Severity.WARN,
    Finding.OUTLIER_RANGE: Severity.WARN,
    Finding.ZERO_VOLUME: Severity.WARN,
    Finding.ZERO_RANGE: Severity.WARN,
}
assert set(_SEVERITIES) == set(Finding)


@dataclass(frozen=True, slots=True)
class QualityFinding:
    code: Finding
    ts_event: int
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def severity(self) -> Severity:
        return _SEVERITIES[self.code]

    def to_document(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "severity": self.severity.value,
            "ts_event": self.ts_event,
            "message": self.message,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class QualityReport:
    bar_type: str
    timeframe: str
    bar_count: int
    start_ns: int | None
    end_ns: int | None
    counts: dict[str, int]
    findings: list[QualityFinding]

    @property
    def failed(self) -> bool:
        return any(finding.severity is Severity.FAIL for finding in self.findings)

    @property
    def failures(self) -> list[QualityFinding]:
        return [f for f in self.findings if f.severity is Severity.FAIL]

    def to_document(self) -> dict[str, Any]:
        return {
            "bar_type": self.bar_type,
            "timeframe": self.timeframe,
            "bar_count": self.bar_count,
            "start_ns": self.start_ns,
            "end_ns": self.end_ns,
            "failed": self.failed,
            "counts": self.counts,
            "findings": [finding.to_document() for finding in self.findings],
        }

    def describe(self) -> str:
        if not self.counts:
            return f"{self.bar_type}: {self.bar_count} bars, clean"
        issues = ", ".join(f"{code}={count}" for code, count in sorted(self.counts.items()))
        return f"{self.bar_type}: {self.bar_count} bars, {issues}"


def _median(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def check_quality(
    bars: Sequence[Bar],
    timeframe: Timeframe,
    *,
    outlier_multiple: Decimal = DEFAULT_OUTLIER_MULTIPLE,
) -> QualityReport:
    """Inspect a bar series. Pure -- no I/O, no clock."""
    bar_type = str(bars[0].bar_type) if bars else "unknown"
    counts: dict[str, int] = {}
    findings: list[QualityFinding] = []

    def record(code: Finding, ts_event: int, message: str, **detail: Any) -> None:
        counts[code.value] = counts.get(code.value, 0) + 1
        if counts[code.value] <= MAX_FINDINGS_PER_CODE:
            findings.append(QualityFinding(code, ts_event, message, detail))

    interval_ns = timeframe.nanoseconds
    recent_ranges: deque[Decimal] = deque(maxlen=OUTLIER_WINDOW)
    previous: Bar | None = None

    for bar in bars:
        if previous is not None:
            delta = bar.ts_event - previous.ts_event
            if delta == 0:
                record(
                    Finding.DUPLICATE_TIMESTAMP,
                    bar.ts_event,
                    f"two bars share ts_event {bar.ts_event}",
                )
            elif delta < 0:
                record(
                    Finding.NON_MONOTONIC,
                    bar.ts_event,
                    f"ts_event {bar.ts_event} follows the later {previous.ts_event}",
                    previous_ts_event=previous.ts_event,
                )
            elif delta > interval_ns:
                missing = delta // interval_ns - 1
                record(
                    Finding.GAP,
                    previous.ts_event,
                    f"{missing} bar(s) missing between {previous.ts_event} and {bar.ts_event}",
                    missing_bars=missing,
                    resumes_at=bar.ts_event,
                )

        high, low = bar.high.as_decimal(), bar.low.as_decimal()
        bar_range = high - low

        if bar_range == 0:
            record(Finding.ZERO_RANGE, bar.ts_event, "high equals low")
        if bar.volume.as_decimal() == 0:
            record(Finding.ZERO_VOLUME, bar.ts_event, "zero volume")

        if len(recent_ranges) == OUTLIER_WINDOW:
            baseline = _median(recent_ranges)
            if baseline > 0 and bar_range > baseline * outlier_multiple:
                record(
                    Finding.OUTLIER_RANGE,
                    bar.ts_event,
                    f"range {bar_range} exceeds {outlier_multiple}x the trailing median {baseline}",
                    bar_range=str(bar_range),
                    baseline=str(baseline),
                )
        recent_ranges.append(bar_range)
        previous = bar

    return QualityReport(
        bar_type=bar_type,
        timeframe=timeframe.value,
        bar_count=len(bars),
        start_ns=bars[0].ts_event if bars else None,
        end_ns=bars[-1].ts_event if bars else None,
        counts=counts,
        findings=findings,
    )


def write_report(
    report: QualityReport,
    artifact_path: str,
    *,
    generated_at: datetime | None = None,
) -> str:
    """Persist a report as JSON and return its path.

    Spec section 4.3 says these go "to Postgres"; section 9.4 forbids this
    service from touching Postgres at all. Resolved the way 9.4 resolves the
    same conflict for backtest results: write the artifact locally, and POST it
    to api-control once that service exists.

    ``generated_at`` is the only non-deterministic field and is kept out of the
    report itself, so two reports over the same bars compare byte for byte.
    """
    stamp = (generated_at or datetime.now(UTC)).isoformat()
    document = {"generated_at": stamp, **report.to_document()}

    fs, base = fsspec.core.url_to_fs(artifact_path.rstrip("/"))
    directory = f"{base}/quality"
    fs.makedirs(directory, exist_ok=True)
    path = f"{directory}/{report.bar_type}.{report.start_ns}-{report.end_ns}.json"
    with fs.open(path, "w") as handle:
        json.dump(document, handle, sort_keys=True, separators=(",", ":"), default=str)
    return str(path)
