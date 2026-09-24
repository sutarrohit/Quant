from __future__ import annotations

import copy
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from engine.settings import Settings
from tests.backtest.conftest import REQUEST
from tests.conftest import AUTH, RecordingQueue, build_client, make_settings
from tests.data.test_binance import EXCHANGE_INFO, EXCHANGE_INFO_BODY

CATALOG_SETTINGS_KWARGS = {"catalog_path": "./catalog"}

requires_btc_catalog = pytest.mark.skipif(
    not Path("catalog/data/bar/BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL").exists(),
    reason="needs the Phase 0 BTC catalog; run `python -m engine.data.ingest`",
)


@pytest.fixture(autouse=True)
def venue() -> Iterator[None]:
    """Binance's exchangeInfo, stubbed: unit tests never reach a venue (rule 15).

    A symbol missing from the catalog is checked against the venue (ADR-003).
    BTCUSDT is listed; anything else answers as Binance does for an unknown symbol.
    """

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("symbol") == "BTCUSDT":
            return httpx.Response(200, json=EXCHANGE_INFO_BODY)
        return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})

    with respx.mock(assert_all_called=False) as router:
        router.get(EXCHANGE_INFO).mock(side_effect=answer)
        yield


@pytest.fixture
def api_settings() -> Settings:
    # The Phase 0 catalog, so the validator's symbol check has something real.
    return make_settings(catalog_path="./catalog", log_level="ERROR")


@pytest.fixture
def api(api_settings: Settings, redis_server: Any, queue: RecordingQueue) -> TestClient:
    return build_client(api_settings, redis_server, queue)


@pytest.fixture
def submission() -> dict[str, Any]:
    payload = copy.deepcopy(REQUEST)
    # A window the Phase 0 catalog actually covers.
    payload["start"] = "2024-01-01T00:00:00Z"
    payload["end"] = "2024-02-01T00:00:00Z"
    return payload


def post(api: TestClient, payload: dict[str, Any]) -> Any:
    return api.post("/v1/backtests", json=payload, headers=AUTH)


# --- authentication ------------------------------------------------------


def test_submission_requires_a_token(api: TestClient, submission: dict[str, Any]) -> None:
    response = api.post("/v1/backtests", json=submission)
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_a_wrong_token_is_rejected(api: TestClient, submission: dict[str, Any]) -> None:
    response = api.post(
        "/v1/backtests", json=submission, headers={"Authorization": "Bearer wrong"}
    )
    assert response.status_code == 401


@pytest.mark.parametrize("route", ["/v1/backtests/job_1", "/v1/catalog/instruments"])
def test_every_v1_route_is_authenticated(api: TestClient, route: str) -> None:
    assert api.get(route).status_code == 401


def test_health_is_not_authenticated(api: TestClient) -> None:
    # A liveness probe cannot be expected to hold a credential.
    assert api.get("/health").status_code == 200


# --- the happy path ------------------------------------------------------


def test_a_valid_submission_is_accepted_and_enqueued(
    api: TestClient, submission: dict[str, Any], queue: RecordingQueue
) -> None:
    response = post(api, submission)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "QUEUED"
    assert body["jobId"].startswith("job_")
    assert queue.enqueued == [body["jobId"]]


def test_the_job_can_then_be_polled(api: TestClient, submission: dict[str, Any]) -> None:
    job_id = post(api, submission).json()["jobId"]

    body = api.get(f"/v1/backtests/{job_id}", headers=AUTH).json()

    assert body["jobId"] == job_id
    assert body["status"] == "QUEUED"
    assert body["submittedAt"]
    assert body["startedAt"] is None
    assert body["finishedAt"] is None
    assert body["error"] is None
    assert body["result"] is None


def test_an_unknown_job_is_404(api: TestClient) -> None:
    response = api.get("/v1/backtests/job_nope", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["code"] == "JOB_NOT_FOUND"


# --- idempotency ---------------------------------------------------------


def test_a_repeat_submission_returns_the_same_job(
    api: TestClient, submission: dict[str, Any], queue: RecordingQueue
) -> None:
    first = post(api, submission)
    second = post(api, submission)

    assert first.json()["jobId"] == second.json()["jobId"]
    assert second.status_code == 200, "a replay is not a new acceptance"
    assert len(queue.enqueued) == 1, "the work was queued twice"


def test_a_conflicting_payload_is_409(api: TestClient, submission: dict[str, Any]) -> None:
    post(api, submission)
    submission["slippageBps"] = "25"

    response = post(api, submission)

    assert response.status_code == 409
    assert response.json()["code"] == "REQUEST_ID_CONFLICT"


def test_different_request_ids_are_separate_jobs(
    api: TestClient, submission: dict[str, Any], queue: RecordingQueue
) -> None:
    first = post(api, submission).json()["jobId"]
    submission["requestId"] = "req_second"
    second = post(api, submission).json()["jobId"]

    assert first != second
    assert queue.enqueued == [first, second]


# --- rejection before the queue -----------------------------------------


def test_an_invalid_spec_is_422_and_never_queued(
    api: TestClient, submission: dict[str, Any], queue: RecordingQueue
) -> None:
    submission["spec"]["exit"] = {"any": [{"type": "takeProfitPercent", "value": 4}]}

    response = post(api, submission)

    assert response.status_code == 422
    codes = [error["code"] for error in response.json()["errors"]]
    assert "MISSING_STOP_LOSS" in codes
    assert queue.enqueued == [], "a bad spec consumed a worker slot"


def test_every_spec_problem_is_reported(api: TestClient, submission: dict[str, Any]) -> None:
    submission["spec"]["entry"] = {
        "all": [
            {"indicator": "atr", "period": 14, "operator": "greaterThanSma"},
            {"any": []},
        ]
    }
    submission["spec"]["exit"] = {"any": [{"type": "takeProfitPercent", "value": 4}]}

    codes = {error["code"] for error in post(api, submission).json()["errors"]}

    assert {"UNSUPPORTED_OPERATOR", "EMPTY_CONDITION_GROUP", "MISSING_STOP_LOSS"} <= codes


def test_errors_carry_a_path(api: TestClient, submission: dict[str, Any]) -> None:
    submission["spec"]["entry"] = {"all": []}
    errors = post(api, submission).json()["errors"]
    assert any(error["path"] == "entry" for error in errors)


def test_a_symbol_outside_the_catalog_and_the_venue_is_rejected(
    api: TestClient, submission: dict[str, Any]
) -> None:
    # Outside the catalog alone is fine since ADR-003; the venue must not list it either.
    submission["spec"]["market"]["symbols"] = ["NOTA/COIN"]
    codes = [error["code"] for error in post(api, submission).json()["errors"]]
    assert "SYMBOL_NOT_IN_CATALOG" in codes


def test_a_period_longer_than_the_window_is_rejected(
    api: TestClient, submission: dict[str, Any]
) -> None:
    # One month of 15m bars is ~2976; a 5000-period indicator never warms up.
    submission["spec"]["entry"] = {
        "indicator": "rsi", "period": 900, "operator": "greaterThan", "value": 70
    }
    submission["start"] = "2024-01-01T00:00:00Z"
    submission["end"] = "2024-01-03T00:00:00Z"
    codes = [error["code"] for error in post(api, submission).json()["errors"]]
    assert "INDICATOR_PERIOD_TOO_LARGE" in codes


def test_a_malformed_spec_is_422_not_500(api: TestClient, submission: dict[str, Any]) -> None:
    submission["spec"]["entry"] = {"indicator": "macd", "period": 12, "operator": "greaterThan"}
    response = post(api, submission)
    assert response.status_code == 422
    assert "errors" in response.json()


def test_missing_fees_are_rejected(
    api: TestClient, submission: dict[str, Any], queue: RecordingQueue
) -> None:
    # Spec section 7.3: never defaulted to zero.
    del submission["fees"]
    response = post(api, submission)
    assert response.status_code == 422
    assert queue.enqueued == []


def test_missing_slippage_is_rejected(api: TestClient, submission: dict[str, Any]) -> None:
    del submission["slippageBps"]
    assert post(api, submission).status_code == 422


# --- the 100 ms budget ---------------------------------------------------


def test_an_invalid_spec_is_rejected_in_under_100ms(
    api: TestClient, submission: dict[str, Any], queue: RecordingQueue
) -> None:
    """Spec section 7.6.

    Validation runs synchronously so a caller gets fast feedback; if it ever
    grew slow enough to matter, the API would need a different shape.
    """
    submission["spec"]["exit"] = {"any": [{"type": "takeProfitPercent", "value": 4}]}
    post(api, submission)  # warm the catalog read

    elapsed = []
    for index in range(5):
        submission["requestId"] = f"req_timing_{index}"
        start = time.perf_counter()
        response = post(api, submission)
        elapsed.append((time.perf_counter() - start) * 1000)
        assert response.status_code == 422

    worst = max(elapsed)
    assert worst < 100, f"slowest rejection took {worst:.1f} ms"
    assert queue.enqueued == []


# --- the handler never runs a backtest ----------------------------------


def test_the_handler_does_no_blocking_work(
    api: TestClient, submission: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec section 7.1.

    A backtest pins a CPU for minutes. If the handler ever ran one, the event
    loop would block and the service would fall over under two users.
    """
    from nautilus_trader.backtest.node import BacktestNode

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("the request handler constructed a BacktestNode")

    monkeypatch.setattr(BacktestNode, "__init__", explode)
    assert post(api, submission).status_code == 202


def test_submission_returns_quickly(api: TestClient, submission: dict[str, Any]) -> None:
    start = time.perf_counter()
    post(api, submission)
    assert (time.perf_counter() - start) * 1000 < 200


# --- cancellation --------------------------------------------------------


def test_a_queued_job_can_be_cancelled(api: TestClient, submission: dict[str, Any]) -> None:
    job_id = post(api, submission).json()["jobId"]

    response = api.delete(f"/v1/backtests/{job_id}", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert api.get(f"/v1/backtests/{job_id}", headers=AUTH).json()["status"] == "CANCELLED"


def test_cancelling_an_unknown_job_is_404(api: TestClient) -> None:
    assert api.delete("/v1/backtests/job_nope", headers=AUTH).status_code == 404


def test_a_running_job_cannot_be_cancelled(
    api: TestClient, submission: dict[str, Any], fake_redis: Any, api_settings: Settings
) -> None:
    import asyncio

    from engine.store.jobs import JobStore

    job_id = post(api, submission).json()["jobId"]
    asyncio.run(JobStore.from_settings(api_settings, fake_redis).mark_running(job_id))

    response = api.delete(f"/v1/backtests/{job_id}", headers=AUTH)

    assert response.status_code == 409
    assert response.json()["code"] == "JOB_NOT_CANCELLABLE"


# --- catalog -------------------------------------------------------------


@requires_btc_catalog
def test_catalog_lists_what_can_be_backtested(api: TestClient) -> None:
    body = api.get("/v1/catalog/instruments", headers=AUTH).json()

    assert {"instrumentId": "BTCUSDT.BINANCE"} in body["instruments"]
    bar_type = next(
        entry for entry in body["barTypes"]
        if entry["barType"] == "BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL"
    )
    assert bar_type["start"].startswith("2023-01-01")
    assert bar_type["end"].startswith("2025-01-01")
