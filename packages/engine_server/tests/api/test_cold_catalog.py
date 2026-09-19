"""Submitting for a symbol nobody ingested, on a cold catalog."""
from __future__ import annotations

import copy
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


@pytest.fixture
def cold(tmp_path: Path) -> Settings:
    return make_settings(catalog_path=str(tmp_path / "catalog"), log_level="ERROR")


@pytest.fixture
def api(cold: Settings, redis_server: Any, queue: RecordingQueue) -> TestClient:
    return build_client(cold, redis_server, queue)


def payload(symbol: str, instrument: str) -> dict[str, Any]:
    body = copy.deepcopy(REQUEST)
    body["start"] = "2024-01-01T00:00:00Z"
    body["end"] = "2024-02-01T00:00:00Z"
    body["instrumentId"] = instrument
    body["barType"] = f"{instrument}-15-MINUTE-LAST-EXTERNAL"
    body["spec"]["market"]["symbols"] = [symbol]
    return body


@respx.mock
def test_a_listed_symbol_is_accepted_on_a_cold_catalog(api: TestClient, queue: RecordingQueue) -> None:
    respx.get(EXCHANGE_INFO).mock(return_value=httpx.Response(200, json=EXCHANGE_INFO_BODY))
    response = api.post("/v1/backtests", json=payload("SOL/USDT", "SOLUSDT.BINANCE"), headers=AUTH)
    print("listed  ->", response.status_code, response.json())
    assert response.status_code == 202
    assert queue.enqueued


@respx.mock
def test_an_unlisted_symbol_is_still_a_422(api: TestClient) -> None:
    respx.get(EXCHANGE_INFO).mock(return_value=httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."}))
    response = api.post("/v1/backtests", json=payload("NOTA/COIN", "NOTACOIN.BINANCE"), headers=AUTH)
    print("unlisted->", response.status_code, response.json())
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "SYMBOL_NOT_IN_CATALOG"
