"""`explain`: each leaf of a rule, and whether it holds on this bar."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from engine.dsl.interpreter import EvalContext, evaluate, explain
from engine.types.dsl import StrategySpec


def spec(entry: dict[str, Any]) -> StrategySpec:
    return StrategySpec.model_validate(
        {
            "strategyId": "x",
            "version": 1,
            "market": {"exchange": "binance", "marketType": "spot", "symbols": ["SOL/USDT"], "timeframe": "15m"},
            "entry": entry,
            "exit": {"any": [{"type": "takeProfitPercent", "value": "4"}, {"type": "stopLossPercent", "value": "2"}]},
            "sizing": {"type": "riskPercent", "riskPercent": "1"},
        }
    )


ENTRY = {
    "all": [
        {"indicator": "rsi", "period": 14, "operator": "crossesAbove", "value": "30"},
        {"indicator": "volume", "operator": "greaterThanSma", "period": 20},
        {"not": {"indicator": "sma", "period": 10, "operator": "crossesAbove", "reference": {"indicator": "sma", "period": 50}}},
    ]
}

FLAT = EvalContext(
    values={"rsi:14": 41.2, "volume": 100, "volumeSma:20": 90, "sma:10": 5, "sma:50": 6},
    previous={"rsi:14": 40, "sma:10": 4, "sma:50": 6},
    close=Decimal(100),
)


def test_every_leaf_is_reported_with_its_path_and_series() -> None:
    results = explain(spec(ENTRY).entry, FLAT, "entry")

    assert [(r.path, r.label, r.passed, r.series) for r in results] == [
        ("entry.all[0]", "rsi(14) crossesAbove 30", False, "rsi:14"),
        ("entry.all[1]", "volume greaterThanSma(20)", True, "volume"),
        ("entry.all[2].not", "sma(10) crossesAbove sma(50)", False, "sma:10"),
    ]


def test_groups_are_left_out_their_answer_follows_from_the_leaves() -> None:
    paths = [r.path for r in explain(spec(ENTRY).entry, FLAT, "entry")]

    assert "entry" not in paths and "entry.all[2]" not in paths


def test_it_agrees_with_evaluate_on_every_leaf() -> None:
    root = spec(ENTRY).entry
    for result, leaf in zip(explain(root, FLAT, "entry"), [root.all_[0], root.all_[1], root.all_[2].not_], strict=True):  # type: ignore[union-attr]
        assert result.passed == evaluate(leaf, FLAT)


def test_exits_read_the_position() -> None:
    held = EvalContext(values={}, previous={}, close=Decimal(103), in_position=True, entry_price=Decimal(100))

    results = explain(spec(ENTRY).exit_, held, "exit")

    assert [(r.label, r.passed, r.series) for r in results] == [
        ("take profit at +4%", False, None),
        ("stop loss at -2%", False, None),
    ]
