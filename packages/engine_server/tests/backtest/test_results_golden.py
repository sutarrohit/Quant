"""The Step 16 gate: a golden summary on a fixed dataset.

A diff here means the numbers a caller receives changed. That must be a
deliberate act — every stored result was produced by the code this file pins.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from engine.backtest.request import BacktestRequest
from engine.backtest.runner import execute
from engine.settings import Settings
from tests.backtest.conftest import REQUEST

GOLDEN = Path("tests/fixtures/backtest_summary.golden.json")
CATALOG = Path("catalog")

pytestmark = pytest.mark.skipif(
    not (CATALOG / "data" / "bar" / "BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL").exists(),
    reason="needs the Phase 0 catalog",
)


@pytest.fixture
def fixed_request() -> BacktestRequest:
    payload = copy.deepcopy(REQUEST)
    payload["start"] = "2024-01-01T00:00:00Z"
    payload["end"] = "2024-02-01T00:00:00Z"
    return BacktestRequest.model_validate(payload)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None, catalog_path="./catalog", internal_api_key="x", log_level="ERROR"
    )


def test_summary_matches_the_golden_file(
    fixed_request: BacktestRequest, settings: Settings
) -> None:
    produced: dict[str, Any] = execute(fixed_request, settings).summary

    if not GOLDEN.exists():  # pragma: no cover - first run only
        GOLDEN.write_text(json.dumps(produced, indent=2, sort_keys=True) + "\n")
        pytest.fail(f"wrote a new golden file at {GOLDEN}; review and re-run")

    assert produced == json.loads(GOLDEN.read_text())


def test_the_summary_is_stable_across_runs(
    fixed_request: BacktestRequest, settings: Settings
) -> None:
    assert execute(fixed_request, settings).summary == execute(fixed_request, settings).summary


def test_costs_split_two_to_one_at_ten_and_five_bps(
    fixed_request: BacktestRequest, settings: Settings
) -> None:
    # The request charges 10 bps of fees and 5 of slippage, so the totals must
    # stand in exactly that ratio — the split is arithmetic, not an estimate.
    from decimal import Decimal

    summary = execute(fixed_request, settings).summary
    fees = Decimal(summary["totalFees"])
    slippage = Decimal(summary["totalSlippage"])

    assert fees > 0
    assert abs(fees / slippage - 2) < Decimal("0.0001")


def test_series_are_not_inlined_in_the_result(
    fixed_request: BacktestRequest, settings: Settings
) -> None:
    # Spec section 7.5: a 50k-row equity curve is never inlined in JSON.
    outcome = execute(fixed_request, settings)
    assert "trades" not in outcome.to_result()
    assert "equityCurve" not in outcome.to_result()
    # They still cross the process boundary, on their way to Parquet.
    assert outcome.to_payload()["trades"]
