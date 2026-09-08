"""Result series on disk (spec section 7.5).

Equity curve, drawdown and the per-trade table go to Parquet under
``NT_ARTIFACT_PATH``. The API returns the summary plus references to these --
**a 50,000-row equity curve is never inlined in JSON**, because a caller
polling for a status should not receive a megabyte of series it did not ask
for.

Written through fsspec, so ``NT_ARTIFACT_PATH`` may be a local directory or an
object-storage URI. Money is written as strings: a Parquet float column would
undo the ``Decimal`` discipline the rest of the pipeline maintains.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import fsspec
import pyarrow as pa
import pyarrow.parquet as pq

from engine.backtest.results import EquityPoint, Summary, Trade
from engine.settings import Settings

#: One directory per job, so everything about a run is in one place and a
#: retention sweep can drop it wholesale.
JOB_PREFIX = "backtests"


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


class ArtifactStore:
    def __init__(self, root: str) -> None:
        self.root = root.rstrip("/")
        self._fs, self._base = fsspec.core.url_to_fs(self.root)

    @classmethod
    def from_settings(cls, settings: Settings) -> ArtifactStore:
        return cls(settings.artifact_path)

    def directory_for(self, job_id: str) -> str:
        return f"{self._base}/{JOB_PREFIX}/{job_id}"

    def write(
        self,
        job_id: str,
        *,
        summary: Summary,
        trades: list[Trade],
        equity_curve: list[EquityPoint],
    ) -> ArtifactSet:
        return self.write_rows(
            job_id,
            summary=summary.to_dict(),
            trades=[trade.to_row() for trade in trades],
            equity_curve=[point.to_row() for point in equity_curve],
        )

    def write_rows(
        self,
        job_id: str,
        *,
        summary: dict[str, Any],
        trades: list[dict[str, Any]],
        equity_curve: list[dict[str, Any]],
    ) -> ArtifactSet:
        """Persist already-serialised rows.

        The worker receives these as plain dicts across a process boundary, so
        it has no ``Trade`` objects to hand back.
        """
        directory = self.directory_for(job_id)
        self._fs.makedirs(directory, exist_ok=True)

        summary_path = f"{directory}/summary.json"
        with self._fs.open(summary_path, "w") as handle:
            json.dump(summary, handle, sort_keys=True, separators=(",", ":"))

        return ArtifactSet(
            job_id=job_id,
            trades=self._write_rows(f"{directory}/trades.parquet", trades),
            equity_curve=self._write_rows(f"{directory}/equity_curve.parquet", equity_curve),
            summary=summary_path,
        )

    def _write_rows(self, path: str, rows: list[dict[str, Any]]) -> str | None:
        """Write rows to Parquet, or nothing at all when there are none.

        An empty file would have no schema to infer and would read back as a
        different shape than a populated one.
        """
        if not rows:
            return None
        table = pa.Table.from_pylist(rows)
        with self._fs.open(path, "wb") as handle:
            pq.write_table(table, handle)
        return path

    def read_rows(self, path: str) -> list[dict[str, Any]]:
        with self._fs.open(path, "rb") as handle:
            return list(pq.read_table(handle).to_pylist())

    def read_summary(self, job_id: str) -> dict[str, Any]:
        with self._fs.open(f"{self.directory_for(job_id)}/summary.json", "r") as handle:
            document: dict[str, Any] = json.load(handle)
        return document
