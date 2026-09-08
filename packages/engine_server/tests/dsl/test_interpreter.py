from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
from dataclasses import fields
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from engine.dsl.interpreter import EvalContext, InterpreterError, evaluate
from engine.dsl.schema import (
    AllGroup,
    AnyGroup,
    NotGroup,
    Operator,
    RsiCondition,
    StopLossPercent,
    TakeProfitPercent,
    VolumeCondition,
)


def ctx(
    values: dict[str, float] | None = None,
    previous: dict[str, float] | None = None,
    *,
    close: str = "100",
    in_position: bool = False,
    entry_price: str | None = None,
) -> EvalContext:
    return EvalContext(
        values=values or {},
        previous=previous or {},
        close=Decimal(close),
        in_position=in_position,
        entry_price=Decimal(entry_price) if entry_price else None,
    )


def rsi(operator: Operator, value: float | None = 30, period: int = 14) -> RsiCondition:
    payload: dict[str, Any] = {"indicator": "rsi", "period": period, "operator": operator}
    if value is not None:
        payload["value"] = value
    return RsiCondition.model_validate(payload)


TRUE = rsi(Operator.GREATER_THAN, 10)  # rsi:14 = 50 > 10
FALSE = rsi(Operator.LESS_THAN, 10)  # rsi:14 = 50 < 10 is false
BASE = {"rsi:14": 50.0}


# --- comparison operators ------------------------------------------------


@pytest.mark.parametrize(
    ("operator", "current", "threshold", "expected"),
    [
        (Operator.GREATER_THAN, 70.0, 70, False),  # exact equality is not greater
        (Operator.GREATER_THAN, 70.1, 70, True),
        (Operator.GREATER_THAN, 69.9, 70, False),
        (Operator.LESS_THAN, 30.0, 30, False),  # exact equality is not less
        (Operator.LESS_THAN, 29.9, 30, True),
        (Operator.LESS_THAN, 30.1, 30, False),
    ],
)
def test_comparisons_including_exact_equality(
    operator: Operator, current: float, threshold: float, expected: bool
) -> None:
    assert evaluate(rsi(operator, threshold), ctx({"rsi:14": current})) is expected


# --- crossings -----------------------------------------------------------


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (29.0, 31.0, True),  # clean cross
        (30.0, 31.0, True),  # previous exactly on the line still crosses
        (30.0, 30.0, False),  # sitting on the line is not a cross
        (31.0, 32.0, False),  # already above; only the crossing bar is true
        (31.0, 29.0, False),  # wrong direction
        (29.0, 30.0, False),  # reaching the line is not passing it
    ],
)
def test_crosses_above_boundaries(previous: float, current: float, expected: bool) -> None:
    condition = rsi(Operator.CROSSES_ABOVE, 30)
    assert evaluate(condition, ctx({"rsi:14": current}, {"rsi:14": previous})) is expected


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (71.0, 69.0, True),
        (70.0, 69.0, True),
        (70.0, 70.0, False),
        (69.0, 68.0, False),
        (69.0, 71.0, False),
        (71.0, 70.0, False),
    ],
)
def test_crosses_below_boundaries(previous: float, current: float, expected: bool) -> None:
    condition = rsi(Operator.CROSSES_BELOW, 70)
    assert evaluate(condition, ctx({"rsi:14": current}, {"rsi:14": previous})) is expected


def test_crossing_is_false_during_warmup() -> None:
    # No previous value yet. False, not a guess (spec section 5.3).
    assert evaluate(rsi(Operator.CROSSES_ABOVE, 30), ctx({"rsi:14": 31.0})) is False
    assert evaluate(rsi(Operator.CROSSES_BELOW, 70), ctx({"rsi:14": 69.0})) is False


def test_crossing_becomes_evaluable_on_the_second_bar() -> None:
    condition = rsi(Operator.CROSSES_ABOVE, 30)
    assert evaluate(condition, ctx({"rsi:14": 31.0})) is False
    assert evaluate(condition, ctx({"rsi:14": 31.0}, {"rsi:14": 29.0})) is True


# --- sma comparison ------------------------------------------------------


def volume(operator: Operator, period: int | None = None, value: float | None = None) -> VolumeCondition:
    payload: dict[str, Any] = {"indicator": "volume", "operator": operator}
    if period is not None:
        payload["period"] = period
    if value is not None:
        payload["value"] = value
    return VolumeCondition.model_validate(payload)


def test_greater_than_sma_compares_two_series() -> None:
    condition = volume(Operator.GREATER_THAN_SMA, period=20)
    assert evaluate(condition, ctx({"volume": 150.0, "volumeSma:20": 100.0})) is True
    assert evaluate(condition, ctx({"volume": 90.0, "volumeSma:20": 100.0})) is False


def test_less_than_sma_compares_two_series() -> None:
    condition = volume(Operator.LESS_THAN_SMA, period=20)
    assert evaluate(condition, ctx({"volume": 90.0, "volumeSma:20": 100.0})) is True


def test_sma_comparison_ignores_any_threshold() -> None:
    # The reference is the series, not `value`.
    condition = volume(Operator.GREATER_THAN_SMA, period=20, value=999999)
    assert evaluate(condition, ctx({"volume": 150.0, "volumeSma:20": 100.0})) is True


def test_volume_threshold_comparison() -> None:
    assert evaluate(volume(Operator.GREATER_THAN, value=100), ctx({"volume": 150.0})) is True


# --- groups --------------------------------------------------------------


def group(kind: str, children: list[Any]) -> Any:
    model = {"all": AllGroup, "any": AnyGroup}[kind]
    return model.model_validate({kind: children})


def test_all_requires_every_child() -> None:
    assert evaluate(group("all", [TRUE, TRUE]), ctx(BASE)) is True
    assert evaluate(group("all", [TRUE, FALSE]), ctx(BASE)) is False


def test_any_requires_one_child() -> None:
    assert evaluate(group("any", [FALSE, TRUE]), ctx(BASE)) is True
    assert evaluate(group("any", [FALSE, FALSE]), ctx(BASE)) is False


def test_not_inverts() -> None:
    assert evaluate(NotGroup.model_validate({"not": FALSE}), ctx(BASE)) is True
    assert evaluate(NotGroup.model_validate({"not": TRUE}), ctx(BASE)) is False


def test_groups_nest() -> None:
    node = group("all", [TRUE, {"any": [FALSE, {"not": FALSE}]}])
    assert evaluate(node, ctx(BASE)) is True


@pytest.mark.parametrize("kind", ["all", "any"])
def test_an_empty_group_raises(kind: str) -> None:
    # `all([])` is True, which would enter on every bar. Never silently.
    with pytest.raises(InterpreterError, match="is empty"):
        evaluate(group(kind, []), ctx(BASE))


# --- exit conditions -----------------------------------------------------


@pytest.mark.parametrize(
    ("close", "entry", "target", "expected"),
    [
        ("104", "100", 4, True),  # exactly at target
        ("104.01", "100", 4, True),
        ("103.99", "100", 4, False),
        ("96", "100", 4, False),
    ],
)
def test_take_profit(close: str, entry: str, target: int, expected: bool) -> None:
    condition = TakeProfitPercent.model_validate({"type": "takeProfitPercent", "value": target})
    assert evaluate(condition, ctx(close=close, in_position=True, entry_price=entry)) is expected


@pytest.mark.parametrize(
    ("close", "entry", "stop", "expected"),
    [
        ("98", "100", 2, True),  # exactly at the stop
        ("97.99", "100", 2, True),
        ("98.01", "100", 2, False),
        ("104", "100", 2, False),
    ],
)
def test_stop_loss(close: str, entry: str, stop: int, expected: bool) -> None:
    condition = StopLossPercent.model_validate({"type": "stopLossPercent", "value": stop})
    assert evaluate(condition, ctx(close=close, in_position=True, entry_price=entry)) is expected


def test_pnl_is_decimal_not_float() -> None:
    # 0.1 + 0.2 arithmetic in an exit decision is money arithmetic.
    context = ctx(close="100.30", in_position=True, entry_price="100.10")
    assert isinstance(context.unrealised_pnl_percent, Decimal)


def test_exit_condition_while_flat_raises() -> None:
    # An exit condition in an entry group is a broken strategy. The validator
    # catches it in Step 9; this is the backstop.
    condition = TakeProfitPercent.model_validate({"type": "takeProfitPercent", "value": 4})
    with pytest.raises(InterpreterError, match="while flat"):
        evaluate(condition, ctx())


def test_non_positive_entry_price_raises() -> None:
    condition = StopLossPercent.model_validate({"type": "stopLossPercent", "value": 2})
    with pytest.raises(InterpreterError, match="must be positive"):
        evaluate(condition, ctx(in_position=True, entry_price="0"))


# --- nothing is swallowed ------------------------------------------------


def test_a_missing_series_raises() -> None:
    with pytest.raises(InterpreterError, match="was not supplied"):
        evaluate(rsi(Operator.GREATER_THAN, 30), ctx({}))


def test_an_unknown_indicator_raises() -> None:
    class Fake:
        indicator = "macd"
        operator = Operator.GREATER_THAN
        period = 14
        value = Decimal(1)

    with pytest.raises(Exception, match="unknown indicator"):
        evaluate(Fake(), ctx({"macd:14": 1.0}))


def test_a_comparison_without_a_threshold_raises() -> None:
    condition = volume(Operator.GREATER_THAN)  # no `value`
    with pytest.raises(InterpreterError, match="needs a `value`"):
        evaluate(condition, ctx({"volume": 5.0}))


def test_an_unevaluable_node_raises() -> None:
    with pytest.raises(InterpreterError, match="cannot evaluate node"):
        evaluate(object(), ctx())


# --- no lookahead --------------------------------------------------------


class StrictMapping(Mapping[str, float]):
    """A mapping that refuses any key it was not given, and records reads."""

    def __init__(self, data: dict[str, float]) -> None:
        self._data = data
        self.reads: list[str] = []

    def __getitem__(self, key: str) -> float:
        self.reads.append(key)
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        raise AssertionError("the interpreter must not iterate the value mapping")

    def __len__(self) -> int:
        raise AssertionError("the interpreter must not size the value mapping")


def test_the_interpreter_reads_only_the_series_it_names() -> None:
    # Iterating or sizing the mapping would mean reaching for values a
    # condition did not name -- the shape a lookahead bug takes here.
    values = StrictMapping({"rsi:14": 50.0})
    context = EvalContext(values=values, previous={}, close=Decimal(100))
    assert evaluate(rsi(Operator.GREATER_THAN, 10), context) is True
    assert values.reads == ["rsi:14"]


def test_the_context_cannot_hold_a_future_bar() -> None:
    # Structural guard: a field holding a bar series would eventually be
    # indexed. If a field is added here, this test must be reconsidered.
    assert {field.name for field in fields(EvalContext)} == {
        "values",
        "previous",
        "close",
        "in_position",
        "entry_price",
    }


def test_the_interpreter_is_pure() -> None:
    # Spec section 5.3: no I/O, no clock, no Nautilus. Checked at the import
    # level so it cannot drift.
    source = Path("src/engine/dsl/interpreter.py").read_text()
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert "nautilus_trader" not in imported
    for banned in ("random", "datetime", "time", "logging", "os", "pathlib", "httpx"):
        assert banned not in imported, f"interpreter imports {banned}"


def test_evaluation_has_no_side_effects() -> None:
    values = {"rsi:14": 50.0}
    previous = {"rsi:14": 20.0}
    context = ctx(values, previous)
    node = group("all", [TRUE, {"any": [FALSE, rsi(Operator.CROSSES_ABOVE, 30)]}])

    first = evaluate(node, context)
    second = evaluate(node, context)

    assert first == second
    assert values == {"rsi:14": 50.0}
    assert previous == {"rsi:14": 20.0}
