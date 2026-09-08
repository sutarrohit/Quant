from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from engine.backtest.request import BacktestRequest


def build(payload: dict[str, Any]) -> BacktestRequest:
    return BacktestRequest.model_validate(payload)


def test_parses_the_documented_shape(request_dict: dict[str, Any]) -> None:
    request = build(request_dict)
    assert request.request_id == "req_01K000000000000000000000"
    assert request.venue == "BINANCE"
    assert request.starting_balances == ["10000 USDT"]
    assert request.fees.taker_bps == Decimal(10)
    assert request.slippage_bps == Decimal(5)


# --- costs are mandatory -------------------------------------------------


def test_omitting_fees_is_rejected(request_dict: dict[str, Any]) -> None:
    # Spec section 7.3: never defaulted to zero. A zero-cost backtest is a
    # marketing number, and nothing downstream marks it as one.
    del request_dict["fees"]
    with pytest.raises(ValidationError, match="fees"):
        build(request_dict)


def test_omitting_one_side_of_fees_is_rejected(request_dict: dict[str, Any]) -> None:
    del request_dict["fees"]["makerBps"]
    with pytest.raises(ValidationError, match="makerBps"):
        build(request_dict)


def test_omitting_slippage_is_rejected(request_dict: dict[str, Any]) -> None:
    del request_dict["slippageBps"]
    with pytest.raises(ValidationError, match="slippageBps"):
        build(request_dict)


def test_explicit_zero_costs_are_allowed(request_dict: dict[str, Any]) -> None:
    # Stating zero is a choice the caller has made and can be held to.
    # Omitting it is not.
    request_dict["fees"] = {"makerBps": "0", "takerBps": "0"}
    request_dict["slippageBps"] = "0"
    assert build(request_dict).slippage_bps == 0


def test_costs_are_decimal_from_strings(request_dict: dict[str, Any]) -> None:
    request_dict["fees"]["takerBps"] = "7.5"
    request = build(request_dict)
    assert isinstance(request.fees.taker_bps, Decimal)
    assert request.fees.taker_bps == Decimal("7.5")


@pytest.mark.parametrize("value", ["-1", "10001"])
def test_absurd_cost_values_are_rejected(request_dict: dict[str, Any], value: str) -> None:
    request_dict["slippageBps"] = value
    with pytest.raises(ValidationError):
        build(request_dict)


# --- window --------------------------------------------------------------


def test_naive_timestamps_are_rejected(request_dict: dict[str, Any]) -> None:
    # A naive window means a different range on a different machine.
    request_dict["start"] = "2023-01-01T00:00:00"
    with pytest.raises(ValidationError, match="timezone"):
        build(request_dict)


def test_an_inverted_window_is_rejected(request_dict: dict[str, Any]) -> None:
    request_dict["end"] = "2022-01-01T00:00:00Z"
    with pytest.raises(ValidationError, match="end must be after start"):
        build(request_dict)


def test_a_zero_length_window_is_rejected(request_dict: dict[str, Any]) -> None:
    request_dict["end"] = request_dict["start"]
    with pytest.raises(ValidationError):
        build(request_dict)


# --- strictness ----------------------------------------------------------


def test_an_unknown_field_is_rejected(request_dict: dict[str, Any]) -> None:
    request_dict["leverage"] = 10
    with pytest.raises(ValidationError):
        build(request_dict)


def test_a_typo_in_fees_is_rejected(request_dict: dict[str, Any]) -> None:
    request_dict["fees"]["takerBpss"] = "10"
    with pytest.raises(ValidationError):
        build(request_dict)


def test_requests_are_frozen(backtest_request: BacktestRequest) -> None:
    with pytest.raises(ValidationError):
        backtest_request.venue = "KRAKEN"  # type: ignore[misc]


def test_starting_balances_cannot_be_empty(request_dict: dict[str, Any]) -> None:
    request_dict["startingBalances"] = []
    with pytest.raises(ValidationError):
        build(request_dict)


# --- payload hash --------------------------------------------------------


def test_payload_hash_ignores_the_request_id(request_dict: dict[str, Any]) -> None:
    # requestId is the key; the hash is what it points at.
    first = build(request_dict).payload_hash()
    request_dict["requestId"] = "req_different"
    assert build(request_dict).payload_hash() == first


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda d: d.__setitem__("slippageBps", "6"), id="slippage"),
        pytest.param(lambda d: d["fees"].__setitem__("takerBps", "11"), id="fees"),
        pytest.param(lambda d: d.__setitem__("end", "2024-01-01T00:00:00Z"), id="window"),
        pytest.param(lambda d: d.__setitem__("startingBalances", ["5000 USDT"]), id="balances"),
        pytest.param(lambda d: d["spec"].__setitem__("version", 5), id="spec"),
        pytest.param(lambda d: d.__setitem__("strategyVersionId", "sv_other"), id="version_id"),
    ],
)
def test_any_meaningful_change_changes_the_payload_hash(
    request_dict: dict[str, Any], mutate: Any
) -> None:
    baseline = build(request_dict).payload_hash()
    mutate(request_dict)
    assert build(request_dict).payload_hash() != baseline


def test_payload_hash_ignores_key_order(request_dict: dict[str, Any]) -> None:
    baseline = build(request_dict).payload_hash()
    shuffled = dict(reversed(list(copy.deepcopy(request_dict).items())))
    assert build(shuffled).payload_hash() == baseline


def test_payload_hash_is_hex(backtest_request: BacktestRequest) -> None:
    digest = backtest_request.payload_hash()
    assert len(digest) == 64
    int(digest, 16)
