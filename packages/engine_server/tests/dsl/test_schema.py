from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from engine.data.timeframes import Timeframe
from engine.types.dsl import (
    MAX_DEPTH,
    MAX_LEAVES,
    AllGroup,
    AnyGroup,
    NotGroup,
    Operator,
    RsiCondition,
    StopLossPercent,
    StrategySpec,
    VolumeCondition,
    walk,
)
from tests.dsl.conftest import leaves, nested

# --- the documented example ---------------------------------------------


def test_parses_the_spec_example(spec_dict: dict[str, Any]) -> None:
    spec = StrategySpec.model_validate(spec_dict)

    assert spec.strategy_id == "btc-rsi-recovery"
    assert spec.version == 4
    assert spec.market.timeframe is Timeframe.M15
    assert spec.market.symbols == ["BTC/USDT"]
    assert isinstance(spec.entry, AllGroup)
    assert isinstance(spec.exit_, AnyGroup)
    assert spec.sizing.risk_percent == Decimal(1)


def test_leaves_resolve_to_the_right_types(spec_dict: dict[str, Any]) -> None:
    spec = StrategySpec.model_validate(spec_dict)
    assert isinstance(spec.entry, AllGroup)
    assert isinstance(spec.entry.all_[0], RsiCondition)
    assert isinstance(spec.entry.all_[1], VolumeCondition)
    assert isinstance(spec.exit_, AnyGroup)
    assert isinstance(spec.exit_.any_[1], StopLossPercent)
    # An exit group mixes exit conditions and indicator conditions.
    assert isinstance(spec.exit_.any_[2], RsiCondition)


def test_operator_is_a_closed_enum(spec_dict: dict[str, Any]) -> None:
    spec = StrategySpec.model_validate(spec_dict)
    assert isinstance(spec.entry, AllGroup)
    assert spec.entry.all_[0].operator is Operator.CROSSES_ABOVE


# --- extra="forbid" ------------------------------------------------------


def test_a_typo_in_a_field_is_a_hard_error(spec_dict: dict[str, Any]) -> None:
    # stopLosPercent silently ignored is a strategy running without a stop.
    spec_dict["exit"]["any"][1] = {"type": "stopLossPercent", "valu": 2}
    with pytest.raises(ValidationError) as caught:
        StrategySpec.model_validate(spec_dict)
    assert "extra_forbidden" in str(caught.value) or "Extra inputs" in str(caught.value)


def test_an_unknown_top_level_field_is_rejected(spec_dict: dict[str, Any]) -> None:
    spec_dict["leverage"] = 10
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(spec_dict)


def test_an_unknown_market_field_is_rejected(spec_dict: dict[str, Any]) -> None:
    spec_dict["market"]["region"] = "eu"
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(spec_dict)


# --- frozen --------------------------------------------------------------


def test_a_spec_cannot_be_mutated(spec_dict: dict[str, Any]) -> None:
    # The hash is a version identity; an editable spec would let the stored
    # result describe a strategy that no longer exists.
    spec = StrategySpec.model_validate(spec_dict)
    with pytest.raises(ValidationError):
        spec.version = 5  # type: ignore[misc]


# --- complexity limits ---------------------------------------------------


def test_depth_at_the_limit_is_accepted(spec_dict: dict[str, Any]) -> None:
    spec_dict["entry"] = nested(MAX_DEPTH)
    assert walk(StrategySpec.model_validate(spec_dict).entry)[0] == MAX_DEPTH


def test_depth_beyond_the_limit_is_rejected(spec_dict: dict[str, Any]) -> None:
    spec_dict["entry"] = nested(MAX_DEPTH + 1)
    with pytest.raises(ValidationError, match=f"limit is {MAX_DEPTH}"):
        StrategySpec.model_validate(spec_dict)


def test_leaf_count_at_the_limit_is_accepted(spec_dict: dict[str, Any]) -> None:
    spec_dict["entry"] = leaves(MAX_LEAVES)
    assert walk(StrategySpec.model_validate(spec_dict).entry)[1] == MAX_LEAVES


def test_leaf_count_beyond_the_limit_is_rejected(spec_dict: dict[str, Any]) -> None:
    spec_dict["entry"] = leaves(MAX_LEAVES + 1)
    with pytest.raises(ValidationError, match=f"limit is {MAX_LEAVES}"):
        StrategySpec.model_validate(spec_dict)


def test_limits_apply_to_the_exit_group_too(spec_dict: dict[str, Any]) -> None:
    spec_dict["exit"] = nested(MAX_DEPTH + 1)
    with pytest.raises(ValidationError, match="exit nests"):
        StrategySpec.model_validate(spec_dict)


# --- node shapes ---------------------------------------------------------


def test_not_group_parses(spec_dict: dict[str, Any]) -> None:
    spec_dict["entry"] = {"not": {"indicator": "rsi", "period": 14, "operator": "greaterThan", "value": 70}}
    spec = StrategySpec.model_validate(spec_dict)
    assert isinstance(spec.entry, NotGroup)
    assert isinstance(spec.entry.not_, RsiCondition)


def test_a_bare_leaf_is_a_valid_node(spec_dict: dict[str, Any]) -> None:
    spec_dict["entry"] = {"indicator": "rsi", "period": 14, "operator": "greaterThan", "value": 70}
    spec = StrategySpec.model_validate(spec_dict)
    assert isinstance(spec.entry, RsiCondition)
    assert walk(spec.entry) == (1, 1)


def test_an_unrecognisable_node_is_rejected(spec_dict: dict[str, Any]) -> None:
    spec_dict["entry"] = {"maybe": []}
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(spec_dict)


def test_an_unknown_indicator_is_rejected_at_schema_level(spec_dict: dict[str, Any]) -> None:
    spec_dict["entry"] = {"indicator": "macd", "period": 14, "operator": "greaterThan", "value": 1}
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(spec_dict)


def test_an_unknown_operator_is_rejected(spec_dict: dict[str, Any]) -> None:
    spec_dict["entry"]["all"][0]["operator"] = "sortOfAbove"
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(spec_dict)


def test_an_unknown_timeframe_is_rejected(spec_dict: dict[str, Any]) -> None:
    spec_dict["market"]["timeframe"] = "3m"
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(spec_dict)


# --- numbers -------------------------------------------------------------


def test_every_number_is_decimal_except_counts(spec_dict: dict[str, Any]) -> None:
    spec = StrategySpec.model_validate(spec_dict)
    assert isinstance(spec.entry, AllGroup)
    assert isinstance(spec.entry.all_[0].value, Decimal)
    assert isinstance(spec.sizing.risk_percent, Decimal)
    # Counts stay integers.
    assert isinstance(spec.entry.all_[0].period, int)
    assert isinstance(spec.version, int)


def test_a_float_threshold_becomes_decimal_exactly(spec_dict: dict[str, Any]) -> None:
    spec_dict["entry"]["all"][0]["value"] = "29.5"
    spec = StrategySpec.model_validate(spec_dict)
    assert isinstance(spec.entry, AllGroup)
    assert spec.entry.all_[0].value == Decimal("29.5")


@pytest.mark.parametrize("value", [0, -1, 100, 1000])
def test_stop_loss_percent_bounds(spec_dict: dict[str, Any], value: int) -> None:
    spec_dict["exit"] = {"type": "stopLossPercent", "value": value}
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(spec_dict)


@pytest.mark.parametrize("value", [0, -5, 101])
def test_risk_percent_bounds(spec_dict: dict[str, Any], value: int) -> None:
    spec_dict["sizing"]["riskPercent"] = value
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(spec_dict)


@pytest.mark.parametrize("period", [0, 1, 1001, -5])
def test_period_bounds(spec_dict: dict[str, Any], period: int) -> None:
    spec_dict["entry"]["all"][0]["period"] = period
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(spec_dict)


# --- identity fields -----------------------------------------------------


@pytest.mark.parametrize("strategy_id", ["", "has space", "-leading-dash", "semi;colon"])
def test_invalid_strategy_ids(spec_dict: dict[str, Any], strategy_id: str) -> None:
    spec_dict["strategyId"] = strategy_id
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(spec_dict)


def test_version_must_be_positive(spec_dict: dict[str, Any]) -> None:
    spec_dict["version"] = 0
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(spec_dict)


def test_symbols_cannot_be_empty(spec_dict: dict[str, Any]) -> None:
    spec_dict["market"]["symbols"] = []
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(spec_dict)


# --- semantics deliberately left to the validator ------------------------


def test_an_empty_group_parses(spec_dict: dict[str, Any]) -> None:
    # Spec section 5.2 lists "entry group empty" as a *validator* rule, so it
    # gets a SpecError with a path in Step 9 rather than a schema exception.
    spec_dict["entry"] = {"all": []}
    spec = StrategySpec.model_validate(spec_dict)
    assert walk(spec.entry) == (1, 0)


def test_a_nonsensical_operator_pairing_parses(spec_dict: dict[str, Any]) -> None:
    # crossesAbove on a non-series value is nonsense, but it is a semantic
    # error, not a structural one. Step 9 rejects it with a path.
    spec_dict["entry"] = {"indicator": "atr", "period": 14, "operator": "greaterThanSma"}
    StrategySpec.model_validate(spec_dict)
