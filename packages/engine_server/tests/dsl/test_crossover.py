"""Indicator-vs-indicator comparison.

Added in Phase 4, because the DSL could previously only compare an indicator to
a constant -- which excluded the whole moving-average-crossover family, and so
excluded most published strategies from ever being reproduced.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from engine.dsl.indicators import build_series, supported_operators
from engine.dsl.interpreter import EvalContext, evaluate
from engine.dsl.keys import required_refs
from engine.dsl.validator import validate_spec
from engine.types.dsl import CloseCondition, Operator, SeriesReference, SmaCondition, StrategySpec
from engine.types.spec_errors import SpecErrorCode

BASE: dict[str, Any] = {
    "strategyId": "crossover",
    "version": 1,
    "market": {
        "exchange": "binance",
        "marketType": "spot",
        "symbols": ["BTC/USDT"],
        "timeframe": "15m",
    },
    "exit": {"any": [{"type": "stopLossPercent", "value": 2}]},
    "sizing": {"type": "riskPercent", "riskPercent": 1},
}


def spec_with(entry: dict[str, Any]) -> StrategySpec:
    return StrategySpec.model_validate({**BASE, "entry": entry})


def condition(**overrides: Any) -> SmaCondition:
    payload = {"indicator": "sma", "period": 10, "operator": "crossesAbove", **overrides}
    return SmaCondition.model_validate(payload)


def ctx(values: dict[str, float], previous: dict[str, float] | None = None) -> EvalContext:
    return EvalContext(values=values, previous=previous or {}, close=Decimal(100))


# --- schema --------------------------------------------------------------


def test_a_golden_cross_parses() -> None:
    spec = spec_with(
        {
            "indicator": "sma",
            "period": 10,
            "operator": "crossesAbove",
            "reference": {"indicator": "sma", "period": 50},
        }
    )
    assert isinstance(spec.entry, SmaCondition)
    assert spec.entry.reference == SeriesReference(indicator="sma", period=50)


def test_price_against_a_moving_average_parses() -> None:
    spec = spec_with(
        {
            "indicator": "close",
            "operator": "crossesAbove",
            "reference": {"indicator": "sma", "period": 200},
        }
    )
    assert isinstance(spec.entry, CloseCondition)


def test_close_has_no_period_of_its_own() -> None:
    with pytest.raises(ValidationError):
        spec_with({"indicator": "close", "period": 10, "operator": "greaterThan", "value": 1})


def test_close_supports_the_series_operators() -> None:
    assert Operator.CROSSES_ABOVE in supported_operators("close")


# --- validation ----------------------------------------------------------


def test_a_condition_cannot_carry_both_a_value_and_a_reference() -> None:
    errors = validate_spec(
        spec_with(
            {
                "indicator": "sma",
                "period": 10,
                "operator": "crossesAbove",
                "value": 30,
                "reference": {"indicator": "sma", "period": 50},
            }
        )
    )
    assert [e.code for e in errors] == [SpecErrorCode.AMBIGUOUS_COMPARISON]


def test_a_condition_must_carry_one_of_them() -> None:
    errors = validate_spec(spec_with({"indicator": "sma", "period": 10, "operator": "crossesAbove"}))
    assert [e.code for e in errors] == [SpecErrorCode.MISSING_THRESHOLD]


def test_a_periodic_reference_needs_a_period() -> None:
    errors = validate_spec(
        spec_with(
            {
                "indicator": "sma",
                "period": 10,
                "operator": "crossesAbove",
                "reference": {"indicator": "sma"},
            }
        )
    )
    assert errors[0].code is SpecErrorCode.INVALID_REFERENCE
    assert errors[0].path == "entry.reference.period"


def test_a_bar_derived_reference_rejects_a_period() -> None:
    errors = validate_spec(
        spec_with(
            {
                "indicator": "sma",
                "period": 10,
                "operator": "crossesAbove",
                "reference": {"indicator": "close", "period": 50},
            }
        )
    )
    assert errors[0].code is SpecErrorCode.INVALID_REFERENCE


def test_an_sma_operator_cannot_also_take_a_reference() -> None:
    # greaterThanSma already compares against a moving average.
    errors = validate_spec(
        spec_with(
            {
                "indicator": "volume",
                "period": 20,
                "operator": "greaterThanSma",
                "reference": {"indicator": "sma", "period": 50},
            }
        )
    )
    assert SpecErrorCode.AMBIGUOUS_COMPARISON in [e.code for e in errors]


def test_the_reference_warmup_is_counted() -> None:
    # The slow average is what has to fit in the window, not the fast one.
    errors = validate_spec(
        spec_with(
            {
                "indicator": "sma",
                "period": 10,
                "operator": "crossesAbove",
                "reference": {"indicator": "sma", "period": 500},
            }
        ),
        available_bars=200,
    )
    assert errors[0].code is SpecErrorCode.INDICATOR_PERIOD_TOO_LARGE
    assert "500 bars" in errors[0].message


# --- series resolution ---------------------------------------------------


def test_both_series_are_requested() -> None:
    refs = required_refs("sma", Operator.CROSSES_ABOVE, 10, ("sma", 50))
    assert [ref.key for ref in refs] == ["sma:10", "sma:50"]


def test_a_close_reference_has_no_period_in_its_key() -> None:
    refs = required_refs("sma", Operator.CROSSES_ABOVE, 10, ("close", None))
    assert [ref.key for ref in refs] == ["sma:10", "close"]


def test_the_close_series_tracks_the_bar() -> None:
    from tests.dsl.test_rsi_reference import _bar

    series = build_series("close", None)
    assert series.initialized is False
    series.handle_bar(_bar(42000.0))
    assert series.initialized is True
    assert series.value == pytest.approx(42000.0)


# --- interpretation ------------------------------------------------------


def test_a_crossing_compares_against_the_reference_at_each_bar() -> None:
    """Both sides move, so both previous values matter.

    Comparing yesterday's fast average against *today's* slow average would
    report crossings that never happened and miss ones that did.
    """
    node = condition(reference={"indicator": "sma", "period": 50})

    # fast was below slow, now above: a cross.
    crossed = ctx({"sma:10": 101.0, "sma:50": 100.0}, {"sma:10": 99.0, "sma:50": 100.0})
    assert evaluate(node, crossed) is True

    # fast above on both bars: already crossed, not crossing.
    already = ctx({"sma:10": 101.0, "sma:50": 100.0}, {"sma:10": 100.5, "sma:50": 100.0})
    assert evaluate(node, already) is False


def test_a_crossing_uses_the_references_previous_value_not_its_current() -> None:
    # Fast was 99 while slow was 98 -- fast was already ABOVE. Judging it
    # against today's slow value of 100 would wrongly call this a cross.
    node = condition(reference={"indicator": "sma", "period": 50})
    context = ctx({"sma:10": 101.0, "sma:50": 100.0}, {"sma:10": 99.0, "sma:50": 98.0})
    assert evaluate(node, context) is False


def test_a_crossing_is_false_while_either_side_is_warming() -> None:
    node = condition(reference={"indicator": "sma", "period": 50})
    assert evaluate(node, ctx({"sma:10": 101.0, "sma:50": 100.0})) is False
    assert (
        evaluate(node, ctx({"sma:10": 101.0, "sma:50": 100.0}, {"sma:10": 99.0})) is False
    )


def test_a_death_cross() -> None:
    node = condition(operator="crossesBelow", reference={"indicator": "sma", "period": 50})
    crossed = ctx({"sma:10": 99.0, "sma:50": 100.0}, {"sma:10": 101.0, "sma:50": 100.0})
    assert evaluate(node, crossed) is True


def test_a_plain_comparison_against_a_reference() -> None:
    node = condition(operator="greaterThan", reference={"indicator": "sma", "period": 50})
    assert evaluate(node, ctx({"sma:10": 101.0, "sma:50": 100.0})) is True
    assert evaluate(node, ctx({"sma:10": 99.0, "sma:50": 100.0})) is False


def test_price_crossing_a_moving_average() -> None:
    node = CloseCondition.model_validate(
        {
            "indicator": "close",
            "operator": "crossesAbove",
            "reference": {"indicator": "sma", "period": 200},
        }
    )
    crossed = ctx({"close": 101.0, "sma:200": 100.0}, {"close": 99.0, "sma:200": 100.0})
    assert evaluate(node, crossed) is True


def test_a_missing_reference_series_raises() -> None:
    from engine.dsl.interpreter import InterpreterError

    node = condition(reference={"indicator": "sma", "period": 50})
    with pytest.raises(InterpreterError, match="sma:50"):
        evaluate(node, ctx({"sma:10": 101.0}, {"sma:10": 99.0}))


def test_thresholds_still_work() -> None:
    # The old shape must keep behaving; a fixed threshold is its own previous.
    node = condition(operator="crossesAbove", value=30)
    assert evaluate(node, ctx({"sma:10": 31.0}, {"sma:10": 29.0})) is True
    assert evaluate(node, ctx({"sma:10": 31.0}, {"sma:10": 30.5})) is False
