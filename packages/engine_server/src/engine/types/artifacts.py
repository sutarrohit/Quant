"""Where a run's series ended up."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ArtifactSet:
    """Where a run's series ended up."""

    job_id: str
    trades: str | None
    equity_curve: str | None
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "jobId": self.job_id,
            "trades": self.trades,
            "equityCurve": self.equity_curve,
            "summary": self.summary,
        }
