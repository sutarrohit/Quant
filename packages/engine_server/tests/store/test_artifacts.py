from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from engine.settings import Settings
from engine.store.artifacts import ArtifactStore
from engine.types.results import EquityPoint, Summary, Trade

NOW = datetime(2024, 1, 1, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(str(tmp_path / "artifacts"))


def summary() -> Summary:
    return Summary(
        starting_equity=D(10000), ending_equity=D(10500), total_return=D("5"),
        cagr=D("60"), max_drawdown=D("-3"), sharpe=D("1.2"), sortino=D("1.8"),
        win_rate=D("55"), profit_factor=D("1.4"), trade_count=2,
        average_trade=D(250), median_trade=D(250), average_holding_seconds=3600,
        total_fees=D(16), total_slippage=D(8), exposure_percent=D("12.5"),
    )


def trade(pnl: str) -> Trade:
    return Trade(
        entry_time=NOW, exit_time=NOW, side="BUY", quantity=D("0.1"),
        entry_price=D(40000), exit_price=D(42000), pnl=D(pnl), return_pct=D(5),
        commission=D(12), fees=D(8), slippage=D(4), holding_seconds=3600,
    )


def test_a_run_writes_three_artifacts(store: ArtifactStore) -> None:
    written = store.write(
        "job_1",
        summary=summary(),
        trades=[trade("300"), trade("200")],
        equity_curve=[EquityPoint(NOW, D(10300), D(0)), EquityPoint(NOW, D(10500), D(0))],
    )

    assert Path(written.summary).exists()
    assert written.trades is not None and Path(written.trades).exists()
    assert written.equity_curve is not None and Path(written.equity_curve).exists()


def test_trades_round_trip_through_parquet(store: ArtifactStore) -> None:
    written = store.write("job_1", summary=summary(), trades=[trade("300")], equity_curve=[])
    assert written.trades is not None

    rows = store.read_rows(written.trades)

    assert len(rows) == 1
    # Money stays a string: a Parquet float column would undo the Decimal
    # discipline the rest of the pipeline maintains.
    assert rows[0]["pnl"] == "300"
    assert rows[0]["fees"] == "8"
    assert rows[0]["slippage"] == "4"
    assert isinstance(rows[0]["holdingSeconds"], int)


def test_the_summary_round_trips(store: ArtifactStore) -> None:
    store.write("job_1", summary=summary(), trades=[], equity_curve=[])
    assert store.read_summary("job_1")["totalReturn"] == "5"


def test_an_empty_series_writes_no_file(store: ArtifactStore) -> None:
    # An empty Parquet file has no schema to infer and reads back as a
    # different shape than a populated one.
    written = store.write("job_1", summary=summary(), trades=[], equity_curve=[])
    assert written.trades is None
    assert written.equity_curve is None
    assert Path(written.summary).exists()


def test_each_job_gets_its_own_directory(store: ArtifactStore) -> None:
    first = store.write("job_1", summary=summary(), trades=[trade("1")], equity_curve=[])
    second = store.write("job_2", summary=summary(), trades=[trade("2")], equity_curve=[])

    assert first.trades != second.trades
    assert store.read_rows(first.trades or "")[0]["pnl"] == "1"
    assert store.read_rows(second.trades or "")[0]["pnl"] == "2"


def test_the_summary_file_is_canonical_json(store: ArtifactStore) -> None:
    written = store.write("job_1", summary=summary(), trades=[], equity_curve=[])
    text = Path(written.summary).read_text()
    assert text == json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))


def test_from_settings_uses_the_artifact_path(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, artifact_path=str(tmp_path / "out"))
    assert ArtifactStore.from_settings(settings).root == str(tmp_path / "out")


def test_references_are_returned_not_the_rows(store: ArtifactStore) -> None:
    # Spec section 7.5: the API returns the summary plus references, never a
    # 50k-row curve inline.
    written = store.write("job_1", summary=summary(), trades=[trade("1")], equity_curve=[])
    document = written.to_dict()
    assert set(document) == {"jobId", "trades", "equityCurve", "summary"}
    assert all(value is None or isinstance(value, str) for value in document.values())
