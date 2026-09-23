"""Serving a finished run's equity curve and trade table.

The two path segments name a directory and a file between them, so these tests
care as much about what is refused as about what comes back.
"""

from __future__ import annotations

from typing import Any

import fakeredis
import pytest
from fastapi.testclient import TestClient

from engine.settings import Settings
from engine.store.artifacts import ArtifactStore
from tests.conftest import AUTH, RecordingQueue, build_client

JOB = "job_" + "ab" * 16

EQUITY = [
    {"time": "2024-01-02T00:00:00+00:00", "equity": "10050.00000000", "drawdown": "0.000000"},
    {"time": "2024-01-03T00:00:00+00:00", "equity": "9980.00000000", "drawdown": "-0.696517"},
    {"time": "2024-01-04T00:00:00+00:00", "equity": "10120.00000000", "drawdown": "0.000000"},
]

TRADES = [
    {
        "entryTime": "2024-01-01T00:00:00+00:00",
        "exitTime": "2024-01-02T00:00:00+00:00",
        "side": "LONG",
        "quantity": "0.5",
        "entryPrice": "42000.00",
        "exitPrice": "42100.00",
        "pnl": "50.00000000",
        "returnPct": "0.238095",
        "commission": "4.20",
        "fees": "2.10000000",
        "slippage": "2.10000000",
        "holdingSeconds": 86400,
    }
]


@pytest.fixture
def api(
    settings: Settings, redis_server: fakeredis.FakeServer, queue: RecordingQueue
) -> TestClient:
    return build_client(settings, redis_server, queue)


@pytest.fixture
def store(settings: Settings) -> ArtifactStore:
    return ArtifactStore.from_settings(settings)


@pytest.fixture
def finished_job(store: ArtifactStore) -> str:
    """A run that wrote all three artifacts, as the worker would have."""
    store.write_rows(JOB, summary={"totalReturn": "1.2"}, trades=TRADES, equity_curve=EQUITY)
    return JOB


def get(api: TestClient, job_id: str, name: str, **params: Any) -> Any:
    return api.get(f"/v1/backtests/{job_id}/artifacts/{name}", params=params, headers=AUTH)


# --- authentication ------------------------------------------------------


def test_it_requires_a_token(api: TestClient, finished_job: str) -> None:
    response = api.get(f"/v1/backtests/{finished_job}/artifacts/equity_curve")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


# --- the happy path ------------------------------------------------------


def test_the_equity_curve_comes_back_in_order(api: TestClient, finished_job: str) -> None:
    body = get(api, finished_job, "equity_curve").json()

    assert body["total"] == 3
    assert [row["time"] for row in body["rows"]] == [row["time"] for row in EQUITY]


def test_the_trade_table_comes_back(api: TestClient, finished_job: str) -> None:
    body = get(api, finished_job, "trades").json()

    assert body["total"] == 1
    assert body["rows"][0]["side"] == "LONG"


def test_money_survives_as_a_string(api: TestClient, finished_job: str) -> None:
    # A float here undoes the Decimal discipline: 10050.0 is not 10050.00000000.
    row = get(api, finished_job, "equity_curve").json()["rows"][0]

    assert row["equity"] == "10050.00000000"
    assert isinstance(row["equity"], str)


# --- paging --------------------------------------------------------------


def test_a_page_is_a_window_onto_the_whole_series(api: TestClient, finished_job: str) -> None:
    body = get(api, finished_job, "equity_curve", offset=1, limit=1).json()

    assert body["rows"] == [EQUITY[1]]
    # `total` is the series, not the page.
    assert body["total"] == 3
    assert (body["offset"], body["limit"]) == (1, 1)


def test_an_offset_past_the_end_is_empty_rather_than_an_error(
    api: TestClient, finished_job: str
) -> None:
    body = get(api, finished_job, "equity_curve", offset=500).json()

    assert body["rows"] == []
    assert body["total"] == 3


def test_a_limit_past_the_ceiling_is_refused(api: TestClient, finished_job: str) -> None:
    # Without a ceiling this is a request to serialise an entire curve, which
    # is the thing Parquet storage avoids.
    assert get(api, finished_job, "equity_curve", limit=10_001).status_code == 422


# --- what is refused, and when ------------------------------------------


def test_an_unknown_artifact_is_refused_before_any_storage_is_touched(
    api: TestClient, finished_job: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Against S3 every probe is a round trip, so a name that cannot match must
    # cost nothing. Blowing up on contact proves the order.
    def explode(*_: object, **__: object) -> bool:
        raise AssertionError("storage was touched for an unknown artifact name")

    monkeypatch.setattr(ArtifactStore, "job_exists", explode)

    response = get(api, finished_job, "summary")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert response.json()["details"]["known"] == ["equity_curve", "trades"]


@pytest.mark.parametrize(
    "name",
    [
        "..%2f..%2f..%2fetc%2fpasswd",
        "%2e%2e%2fsummary.json",
        "equity_curve.parquet",
        "equity_curve%00",
    ],
)
def test_a_name_that_is_not_in_the_closed_set_reads_nothing(
    api: TestClient, finished_job: str, name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ArtifactStore, "job_exists", lambda *_, **__: pytest.fail("storage was touched")
    )

    assert api.get(
        f"/v1/backtests/{finished_job}/artifacts/{name}", headers=AUTH
    ).status_code == 404


@pytest.mark.parametrize(
    "job_id",
    [
        "job_1",
        "job_" + "z" * 32,
        "job_" + "ab" * 15,
        "JOB_" + "ab" * 16,
    ],
)
def test_a_job_id_that_is_not_one_we_minted_reads_nothing(
    api: TestClient, job_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # job_id becomes a directory. "../.." is a perfectly good string, so the
    # shape is checked rather than trusted.
    monkeypatch.setattr(
        ArtifactStore, "job_exists", lambda *_, **__: pytest.fail("storage was touched")
    )

    response = api.get(f"/v1/backtests/{job_id}/artifacts/trades", headers=AUTH)

    assert response.status_code == 404
    assert response.json()["code"] == "JOB_NOT_FOUND"


@pytest.mark.parametrize("job_id", ["..%2f..%2fetc", "%2e%2e%2f%2e%2e", "..", "."])
def test_a_traversal_in_the_job_id_reads_nothing(
    api: TestClient, job_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # These never reach the handler: an encoded slash is decoded before routing,
    # so the app's own 404 answers. Refused either way, and nothing opened.
    monkeypatch.setattr(
        ArtifactStore, "job_exists", lambda *_, **__: pytest.fail("storage was touched")
    )

    assert api.get(
        f"/v1/backtests/{job_id}/artifacts/trades", headers=AUTH
    ).status_code == 404


def test_a_job_that_wrote_nothing_is_not_found(api: TestClient) -> None:
    response = get(api, "job_" + "cd" * 16, "equity_curve")

    assert response.status_code == 404
    assert response.json()["code"] == "JOB_NOT_FOUND"


def test_a_run_with_no_trades_is_an_empty_series_not_a_missing_one(
    api: TestClient, store: ArtifactStore
) -> None:
    # write_rows skips a file with no rows, so a strategy that never fired has
    # no trades.parquet. A 404 would show an error for a valid backtest.
    store.write_rows(JOB, summary={"tradeCount": "0"}, trades=[], equity_curve=EQUITY)

    body = get(api, JOB, "trades").json()

    assert body == {"rows": [], "total": 0, "offset": 0, "limit": 1_000}
