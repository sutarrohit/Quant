from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest

from engine.dsl.hashing import spec_hash
from engine.strategies.dsl_strategy import DslStrategy, DslStrategyConfig
from engine.types.dsl import StrategySpec
from tests.strategies.conftest import (
    BAR_TYPE,
    INSTRUMENT_ID,
    evaluations,
    requires_catalog,
    run_backtest,
    signals,
)


def make_config(spec: dict[str, Any]) -> DslStrategyConfig:
    return DslStrategyConfig(
        instrument_id=INSTRUMENT_ID,  # type: ignore[arg-type]
        bar_type=BAR_TYPE,  # type: ignore[arg-type]
        spec=spec,
        strategy_version_id="sv_test",
        spec_hash=spec_hash(StrategySpec.model_validate(spec)),
    )


# --- config and construction --------------------------------------------


def test_config_decodes_ids_from_strings(rsi_spec: dict[str, Any]) -> None:
    # msgspec decodes InstrumentId and BarType from their string forms, which
    # is what lets a spec travel from the caller as plain JSON.
    config = make_config(rsi_spec)
    assert str(config.instrument_id) == INSTRUMENT_ID
    assert str(config.bar_type) == BAR_TYPE


def test_config_is_frozen(rsi_spec: dict[str, Any]) -> None:
    config = make_config(rsi_spec)
    with pytest.raises(AttributeError):
        config.spec_hash = "other"  # type: ignore[misc]


def test_strategy_parses_its_spec(rsi_spec: dict[str, Any]) -> None:
    strategy = DslStrategy(make_config(rsi_spec))
    assert strategy.spec.strategy_id == "btc-rsi-recovery"


def test_a_malformed_spec_fails_at_construction(rsi_spec: dict[str, Any]) -> None:
    # Better here than as a mysteriously empty result later.
    rsi_spec["entry"]["all"][0]["indicator"] = "macd"
    with pytest.raises(Exception, match="validation error|discriminator|tag"):
        DslStrategy(make_config(rsi_spec))


# --- series resolution ---------------------------------------------------


def test_identical_conditions_share_one_series(rsi_spec: dict[str, Any]) -> None:
    # rsi:14 appears in both entry and exit; computing it twice would let the
    # two copies drift.
    strategy = DslStrategy(make_config(rsi_spec))
    series = strategy._build_series()
    assert sorted(series) == ["rsi:14"]


def test_distinct_periods_get_distinct_series(rsi_spec: dict[str, Any]) -> None:
    rsi_spec["entry"] = {
        "all": [
            {"indicator": "sma", "period": 10, "operator": "greaterThan", "value": 1},
            {"indicator": "sma", "period": 50, "operator": "lessThan", "value": 1},
        ]
    }
    rsi_spec["exit"] = {"any": [{"type": "stopLossPercent", "value": 2}]}
    strategy = DslStrategy(make_config(rsi_spec))
    assert sorted(strategy._build_series()) == ["sma:10", "sma:50"]


def test_series_are_collected_from_entry_and_exit(rsi_spec: dict[str, Any]) -> None:
    # An indicator used only in the exit tree still has to be built and warmed,
    # or the exit could never be evaluated.
    rsi_spec["entry"] = {"indicator": "sma", "period": 10, "operator": "greaterThan", "value": 1}
    rsi_spec["exit"] = {
        "any": [
            {"type": "stopLossPercent", "value": 2},
            {"indicator": "atr", "period": 30, "operator": "greaterThan", "value": 5},
        ]
    }
    strategy = DslStrategy(make_config(rsi_spec))
    assert sorted(strategy._build_series()) == ["atr:30", "sma:10"]


def test_sma_comparison_builds_the_reference_series(rsi_spec: dict[str, Any]) -> None:
    rsi_spec["entry"] = {"indicator": "volume", "operator": "greaterThanSma", "period": 20}
    rsi_spec["exit"] = {"any": [{"type": "stopLossPercent", "value": 2}]}
    strategy = DslStrategy(make_config(rsi_spec))
    assert sorted(strategy._build_series()) == ["volume", "volumeSma:20"]


def test_warmup_is_the_longest_series(rsi_spec: dict[str, Any]) -> None:
    rsi_spec["entry"] = {
        "all": [
            {"indicator": "sma", "period": 10, "operator": "greaterThan", "value": 1},
            {"indicator": "ema", "period": 200, "operator": "lessThan", "value": 1},
        ]
    }
    rsi_spec["exit"] = {"any": [{"type": "stopLossPercent", "value": 2}]}
    assert DslStrategy(make_config(rsi_spec)).warmup_bars == 200


# --- end to end in a real BacktestNode ----------------------------------


@requires_catalog
def test_runs_in_a_backtest_node_and_evaluates_every_bar(rsi_spec: dict[str, Any]) -> None:
    records = run_backtest(rsi_spec)
    evaluated = evaluations(records)

    # 31 days of 15m bars, less the 14-bar RSI warmup.
    assert 2900 < len(evaluated) < 3000
    assert all(record["spec_hash"] == records[0]["spec_hash"] for record in evaluated)


@requires_catalog
def test_signals_actually_fire(rsi_spec: dict[str, Any]) -> None:
    # Zero signals is what a wrongly-scaled indicator looks like, and it is
    # indistinguishable from a strategy that legitimately found none. See
    # docs/nautilus-api-notes.md D7.
    assert len(signals(run_backtest(rsi_spec))) > 10


@requires_catalog
def test_rsi_is_reported_on_the_conventional_scale(rsi_spec: dict[str, Any]) -> None:
    values = [record["values"]["rsi:14"] for record in evaluations(run_backtest(rsi_spec))]
    assert max(values) > 50, "RSI never exceeded 50; it is probably on a 0..1 scale"
    assert all(0 <= value <= 100 for value in values)


@requires_catalog
def test_every_decision_is_traceable(rsi_spec: dict[str, Any]) -> None:
    # This log is what later answers "why did the agent trade".
    record = evaluations(run_backtest(rsi_spec))[0]
    assert record["strategy_version_id"] == "sv_test"
    assert record["spec_hash"] == spec_hash(StrategySpec.model_validate(rsi_spec))
    assert record["instrument_id"] == INSTRUMENT_ID
    assert isinstance(record["ts_event"], int)
    assert record["side"] in {"entry", "exit"}
    assert isinstance(record["triggered"], bool)
    assert "rsi:14" in record["values"]


@requires_catalog
def test_warmup_bars_produce_no_evaluation(rsi_spec: dict[str, Any]) -> None:
    # Evaluating a half-warmed indicator would read a meaningless number.
    rsi_spec["entry"] = {"indicator": "ema", "period": 300, "operator": "greaterThan", "value": 1}
    records = run_backtest(rsi_spec, start="2024-01-01", end="2024-01-03")  # 192 bars < 300
    assert evaluations(records) == []


@requires_catalog
def test_a_never_triggering_spec_evaluates_but_never_fires(rsi_spec: dict[str, Any]) -> None:
    rsi_spec["entry"] = {"indicator": "rsi", "period": 14, "operator": "greaterThan", "value": 999}
    records = run_backtest(rsi_spec)
    assert len(evaluations(records)) > 100
    assert signals(records) == []


@requires_catalog
def test_evaluation_is_deterministic(rsi_spec: dict[str, Any]) -> None:
    # A preview of the Step 11 acceptance gate: the same spec and data must
    # produce the same decisions every time.
    first = [
        (record["ts_event"], record["side"], record["triggered"])
        for record in evaluations(run_backtest(copy.deepcopy(rsi_spec), end="2024-01-08"))
    ]
    second = [
        (record["ts_event"], record["side"], record["triggered"])
        for record in evaluations(run_backtest(copy.deepcopy(rsi_spec), end="2024-01-08"))
    ]
    assert first == second
    assert len(first) > 100


@requires_catalog
def test_entry_and_exit_trees_are_each_evaluated(rsi_spec: dict[str, Any]) -> None:
    # Exactly one tree is evaluated per bar: entry while flat, exit while in a
    # position. Evaluating both would let an entry fire on a bar that is also
    # closing a position.
    records = evaluations(run_backtest(rsi_spec))
    sides = {record["side"] for record in records}
    assert sides == {"entry", "exit"}

    by_timestamp: dict[int, set[str]] = {}
    for record in records:
        by_timestamp.setdefault(record["ts_event"], set()).add(record["side"])
    assert all(len(sides_at) == 1 for sides_at in by_timestamp.values())


@requires_catalog
def test_a_crossover_strategy_runs_end_to_end(rsi_spec: dict[str, Any]) -> None:
    # The whole point of adding indicator-vs-indicator comparison: the
    # moving-average crossover family is now expressible and tradeable.
    rsi_spec["entry"] = {
        "indicator": "sma",
        "period": 10,
        "operator": "crossesAbove",
        "reference": {"indicator": "sma", "period": 50},
    }
    rsi_spec["exit"] = {
        "any": [
            {"type": "stopLossPercent", "value": 3},
            {"type": "takeProfitPercent", "value": 6},
        ]
    }
    records = run_backtest(rsi_spec)

    assert len(evaluations(records)) > 100
    assert len(signals(records)) > 0
    # Both series were built and warmed.
    assert set(evaluations(records)[0]["values"]) == {"sma:10", "sma:50"}


# --- the cost sizing reserves for ----------------------------------------


def build_strategy(spec: dict[str, Any], cost_bps: str) -> Any:
    """A strategy with a given configured cost. `DslStrategyConfig` is a msgspec
    Struct rather than a Pydantic model (D8), so it is rebuilt, not copied."""
    from engine.strategies.dsl_strategy import DslStrategy, DslStrategyConfig

    return DslStrategy(
        DslStrategyConfig(
            instrument_id=INSTRUMENT_ID,  # type: ignore[arg-type]
            bar_type=BAR_TYPE,  # type: ignore[arg-type]
            spec=spec,
            strategy_version_id="sv_test",
            spec_hash=spec_hash(StrategySpec.model_validate(spec)),
            cost_bps=cost_bps,
        )
    )


class FakeInstrument:
    def __init__(self, taker_fee: Decimal | None) -> None:
        self.taker_fee = taker_fee


def resolve(strategy: Any, instrument: FakeInstrument) -> Decimal:
    strategy.instrument = instrument
    strategy._resolve_cost_rate()  # noqa: SLF001
    return strategy.cost_rate


def test_a_configured_cost_wins(rsi_spec: dict[str, Any]) -> None:
    """A backtest states its fees in the request, and they are the contract.

    Rule 5: mandatory, never defaulted. The instrument must not quietly
    override a number the caller asked to be charged.
    """
    strategy = build_strategy(rsi_spec, "15")

    assert resolve(strategy, FakeInstrument(Decimal("0.001"))) == Decimal("0.0015")


def test_the_instrument_supplies_what_the_config_did_not(rsi_spec: dict[str, Any]) -> None:
    """A live node has no request; the venue is the authority.

    Without this a simulation sizes as though trading were free, overdraws the
    account paying a commission it never reserved for, and the exchange halts
    the run -- reporting success for the handful of trades that fit.
    """
    strategy = build_strategy(rsi_spec, "0")

    assert resolve(strategy, FakeInstrument(Decimal("0.001"))) == Decimal("0.001")


def test_an_instrument_with_no_fee_leaves_it_at_zero(rsi_spec: dict[str, Any]) -> None:
    # Zero from both is a real answer -- a venue that charges nothing -- and
    # must not be turned into a guess.
    strategy = build_strategy(rsi_spec, "0")

    assert resolve(strategy, FakeInstrument(Decimal(0))) == Decimal(0)
    assert resolve(strategy, FakeInstrument(None)) == Decimal(0)


def test_the_resolved_cost_is_a_decimal(rsi_spec: dict[str, Any]) -> None:
    # It multiplies notionals in the sizing path, where a float is a rounding
    # error in money (rule 4). Nautilus hands these back as floats (D14).
    strategy = build_strategy(rsi_spec, "0")

    assert isinstance(resolve(strategy, FakeInstrument(0.001)), Decimal)
