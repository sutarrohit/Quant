from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from engine.data.raw import RawRecord, RawStore, payload_digest
from engine.settings import Settings

FETCHED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def record(payload: object, key: str = "BTCUSDT-15m-0-1000") -> RawRecord:
    return RawRecord(
        source="binance",
        endpoint="klines",
        key=key,
        params={"symbol": "BTCUSDT"},
        payload=payload,
        fetched_at=FETCHED_AT,
        response_headers={"x-mbx-used-weight-1m": "12"},
    )


@pytest.fixture
def store(tmp_path: Path) -> RawStore:
    return RawStore(str(tmp_path / "raw"))


def test_digest_ignores_dict_ordering() -> None:
    assert payload_digest({"a": 1, "b": 2}) == payload_digest({"b": 2, "a": 1})


def test_digest_changes_with_content() -> None:
    assert payload_digest([[1, "2"]]) != payload_digest([[1, "3"]])


def test_write_then_read_round_trip(store: RawStore) -> None:
    rows = [[1704067200000, "42000.00", "42100.00", "41900.00", "42050.00", "1.5"]]
    path = store.write(record(rows))

    document = store.read(path)
    assert document["payload"] == rows
    assert document["source"] == "binance"
    assert document["endpoint"] == "klines"
    assert document["params"] == {"symbol": "BTCUSDT"}
    assert document["fetched_at"] == FETCHED_AT.isoformat()
    assert document["response_headers"] == {"x-mbx-used-weight-1m": "12"}
    assert document["payload_sha256"] == payload_digest(rows)


def test_path_is_content_addressed(store: RawStore) -> None:
    path = store.write(record([[1, "2"]]))
    assert path.endswith(".json")
    assert payload_digest([[1, "2"]])[:16] in path
    assert "/binance/klines/" in path


def test_rewriting_identical_data_is_a_no_op(store: RawStore) -> None:
    first = store.write(record([[1, "2"]]))
    original = Path(first).read_bytes()

    # A later fetch of the same window, with a different clock and headers.
    again = RawRecord(
        source="binance",
        endpoint="klines",
        key="BTCUSDT-15m-0-1000",
        params={"symbol": "BTCUSDT"},
        payload=[[1, "2"]],
        fetched_at=datetime(2026, 6, 1, tzinfo=UTC),
        response_headers={"x-mbx-used-weight-1m": "999"},
    )
    second = store.write(again)

    assert second == first
    assert Path(first).read_bytes() == original


def test_a_restatement_lands_beside_the_original(store: RawStore) -> None:
    # Exchanges do revise historical candles. Both versions must survive, or
    # "the data changed under us" becomes unprovable.
    original = store.write(record([[1, "42000.00"]]))
    revised = store.write(record([[1, "42001.00"]]))

    assert original != revised
    assert store.read(original)["payload"] == [[1, "42000.00"]]
    assert store.read(revised)["payload"] == [[1, "42001.00"]]
    assert len(store.list("binance", "klines")) == 2


def test_list_is_sorted_and_scoped(store: RawStore) -> None:
    store.write(record([[1]], key="b-window"))
    store.write(record([[2]], key="a-window"))
    paths = store.list("binance", "klines")
    assert paths == sorted(paths)
    assert store.list("binance", "exchangeInfo") == []
    assert store.list("kraken", "klines") == []


def test_stored_document_is_canonical_json(store: RawStore) -> None:
    # Sorted keys and fixed separators, so an unchanged record produces
    # byte-identical bytes on any machine.
    path = store.write(record([[1, "2"]]))
    text = Path(path).read_text()
    assert text == json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))


def test_from_settings_uses_the_raw_path(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, raw_path=str(tmp_path / "audit"))
    assert RawStore.from_settings(settings).root == str(tmp_path / "audit")
