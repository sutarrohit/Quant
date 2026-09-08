"""Phase 1 acceptance (spec section 5.5).

The property test is the load-bearing one. Schema, validator and interpreter
can each be individually correct and still disagree at the seams: the schema
accepts a shape the interpreter cannot read, or the validator passes a spec
whose evaluation raises. Generating specs and running the whole chain is what
catches that.
"""

from __future__ import annotations

import subprocess
import sys
from decimal import Decimal
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from engine.dsl.hashing import spec_hash
from engine.dsl.interpreter import EvalContext, evaluate
from engine.dsl.keys import required_refs
from engine.dsl.schema import MAX_DEPTH, MAX_LEAVES, Operator, StrategySpec
from engine.dsl.validator import validate_spec

PERIODIC = ["rsi", "sma", "ema", "atr"]
SERIES_OPS = ["crossesAbove", "crossesBelow", "greaterThan", "lessThan"]
VOLUME_OPS = ["greaterThan", "lessThan", "greaterThanSma", "lessThanSma"]


# --- spec generation -----------------------------------------------------


@st.composite
def periodic_condition(draw: st.DrawFn) -> dict[str, Any]:
    return {
        "indicator": draw(st.sampled_from(PERIODIC)),
        "period": draw(st.integers(min_value=2, max_value=50)),
        "operator": draw(st.sampled_from(SERIES_OPS)),
        "value": draw(st.integers(min_value=-100, max_value=100)),
    }


@st.composite
def volume_condition(draw: st.DrawFn) -> dict[str, Any]:
    operator = draw(st.sampled_from(VOLUME_OPS))
    condition: dict[str, Any] = {"indicator": "volume", "operator": operator}
    if operator in ("greaterThanSma", "lessThanSma"):
        condition["period"] = draw(st.integers(min_value=2, max_value=50))
    else:
        condition["value"] = draw(st.integers(min_value=0, max_value=1000))
    return condition


leaf = st.one_of(periodic_condition(), volume_condition())


def tree(max_depth: int) -> st.SearchStrategy[dict[str, Any]]:
    return st.recursive(
        leaf,
        lambda children: st.one_of(
            st.builds(lambda items: {"all": items}, st.lists(children, min_size=1, max_size=3)),
            st.builds(lambda items: {"any": items}, st.lists(children, min_size=1, max_size=3)),
            st.builds(lambda child: {"not": child}, children),
        ),
        max_leaves=6,
    )


@st.composite
def strategy_spec(draw: st.DrawFn) -> dict[str, Any]:
    return {
        "strategyId": draw(st.from_regex(r"\A[a-z][a-z0-9-]{0,20}\Z")),
        "version": draw(st.integers(min_value=1, max_value=99)),
        "market": {
            "exchange": "binance",
            "marketType": "spot",
            "symbols": ["BTC/USDT"],
            "timeframe": draw(st.sampled_from(["1m", "5m", "15m", "1h", "4h", "1d"])),
        },
        "entry": draw(tree(MAX_DEPTH)),
        "exit": {
            "any": [
                {"type": "stopLossPercent", "value": draw(st.integers(min_value=1, max_value=50))},
                draw(tree(MAX_DEPTH - 1)),
            ]
        },
        "sizing": {"type": "riskPercent", "riskPercent": draw(st.integers(min_value=1, max_value=10))},
    }


# --- the property --------------------------------------------------------


def context_for(spec: StrategySpec, *, warm: bool) -> EvalContext:
    """A context supplying every series the spec reads.

    This is what the strategy does in Step 10, done by hand: collect the refs a
    spec implies and provide a value for each. If the interpreter ever reads a
    key the registry did not name, the lookup fails and the property fails.
    """
    values: dict[str, float] = {}
    for node in _leaves(spec):
        for ref in required_refs(node["indicator"], Operator(node["operator"]), node.get("period")):
            values[ref.key] = 42.0
    return EvalContext(
        values=values,
        previous=dict(values) if warm else {},
        close=Decimal("105"),
        in_position=True,
        entry_price=Decimal("100"),
    )


def _leaves(spec: StrategySpec) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if "all" in node:
                for child in node["all"]:
                    visit(child)
            elif "any" in node:
                for child in node["any"]:
                    visit(child)
            elif "not" in node:
                visit(node["not"])
            elif "indicator" in node:
                found.append(node)

    document = spec.model_dump(mode="json", by_alias=True)
    visit(document["entry"])
    visit(document["exit"])
    return found


@given(payload=strategy_spec())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_any_valid_spec_evaluates_without_raising(payload: dict[str, Any]) -> None:
    spec = StrategySpec.model_validate(payload)
    if validate_spec(spec):
        return  # the validator's job is to reject; only accepted specs must run

    for warm in (False, True):
        result = evaluate(spec.entry, context_for(spec, warm=warm))
        assert isinstance(result, bool)
        assert isinstance(evaluate(spec.exit_, context_for(spec, warm=warm)), bool)


@given(payload=strategy_spec())
@settings(max_examples=100, deadline=None)
def test_any_valid_spec_hashes_stably(payload: dict[str, Any]) -> None:
    spec = StrategySpec.model_validate(payload)
    again = StrategySpec.model_validate(spec.model_dump(mode="json", by_alias=True))
    assert spec_hash(again) == spec_hash(spec)


@given(payload=strategy_spec())
@settings(max_examples=100, deadline=None)
def test_the_validator_never_raises_on_a_parseable_spec(payload: dict[str, Any]) -> None:
    spec = StrategySpec.model_validate(payload)
    validate_spec(spec, available_bars=100, known_instruments={"BTCUSDT.BINANCE"})


# --- the remaining section 5.5 criteria ---------------------------------


def test_an_unknown_indicator_is_rejected_before_runtime(spec_dict: dict[str, Any]) -> None:
    # Section 5.5: "rejected at validation, not at runtime". The schema's
    # discriminated union refuses it first, so it never reaches an engine.
    import pytest
    from pydantic import ValidationError

    spec_dict["entry"] = {"indicator": "macd", "period": 12, "operator": "greaterThan", "value": 1}
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(spec_dict)


def test_round_trip_is_byte_identical(spec_dict: dict[str, Any]) -> None:
    from engine.dsl.hashing import canonical_json

    spec = StrategySpec.model_validate(spec_dict)
    again = StrategySpec.model_validate(spec.model_dump(mode="json", by_alias=True))
    assert canonical_json(again) == canonical_json(spec)


def test_hash_is_stable_across_processes(spec_dict: dict[str, Any]) -> None:
    import json

    script = (
        "import json,sys;"
        "from engine.dsl.hashing import spec_hash;"
        "from engine.dsl.schema import StrategySpec;"
        "print(spec_hash(StrategySpec.model_validate(json.loads(sys.argv[1]))))"
    )
    digests = {
        subprocess.run(
            [sys.executable, "-c", script, json.dumps(spec_dict)],
            capture_output=True, text=True, check=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        ).stdout.strip()
        for seed in ("0", "1", "424242")
    }
    assert len(digests) == 1
    assert digests == {spec_hash(StrategySpec.model_validate(spec_dict))}


def test_complexity_limits_are_the_documented_ones() -> None:
    assert (MAX_DEPTH, MAX_LEAVES) == (5, 32)


def test_the_property_test_is_not_vacuous() -> None:
    """Guard against the property silently proving nothing.

    ``test_any_valid_spec_evaluates_without_raising`` returns early for specs
    the validator rejects. If a future change made the validator reject almost
    everything, that test would still pass while exercising nothing. This
    asserts a healthy share of generated specs actually reach the interpreter.
    """
    counts = {"generated": 0, "evaluated": 0}

    @given(payload=strategy_spec())
    @settings(max_examples=200, deadline=None, suppress_health_check=list(HealthCheck))
    def sample(payload: dict[str, Any]) -> None:
        counts["generated"] += 1
        spec = StrategySpec.model_validate(payload)
        if validate_spec(spec):
            return
        evaluate(spec.entry, context_for(spec, warm=True))
        counts["evaluated"] += 1

    sample()

    assert counts["generated"] >= 100
    ratio = counts["evaluated"] / counts["generated"]
    assert ratio > 0.25, f"only {ratio:.0%} of generated specs reached the interpreter"
