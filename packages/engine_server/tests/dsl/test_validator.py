from __future__ import annotations

from typing import Any

import pytest

from engine.dsl.validator import validate_spec
from engine.types.dsl import StrategySpec
from engine.types.spec_errors import SpecError, SpecErrorCode


def spec_of(payload: dict[str, Any]) -> StrategySpec:
    return StrategySpec.model_validate(payload)


def codes(errors: list[SpecError]) -> list[SpecErrorCode]:
    return [error.code for error in errors]


def only(errors: list[SpecError], code: SpecErrorCode) -> SpecError:
    matching = [error for error in errors if error.code is code]
    assert len(matching) == 1, f"expected one {code}, got {codes(errors)}"
    return matching[0]


# --- the documented example is valid ------------------------------------


def test_the_spec_example_validates(spec_dict: dict[str, Any]) -> None:
    assert validate_spec(spec_of(spec_dict)) == []


def test_optional_checks_are_skipped_when_not_configured(spec_dict: dict[str, Any]) -> None:
    # Without a window or a catalog, the pure checks still run and the other
    # two stay quiet rather than guessing.
    assert validate_spec(spec_of(spec_dict), available_bars=None, known_instruments=None) == []


# --- operator pairings ---------------------------------------------------


def test_sma_comparison_on_a_periodic_indicator_is_rejected(spec_dict: dict[str, Any]) -> None:
    # `period` is already the indicator's own on rsi/sma/ema/atr, so
    # greaterThanSma there has no window to average over.
    spec_dict["entry"] = {"indicator": "atr", "period": 14, "operator": "greaterThanSma"}
    error = only(validate_spec(spec_of(spec_dict)), SpecErrorCode.UNSUPPORTED_OPERATOR)
    assert error.path == "entry.operator"
    assert error.observed == "greaterThanSma"
    assert "crossesAbove" in (error.limit or "")


def test_crossing_on_volume_is_rejected(spec_dict: dict[str, Any]) -> None:
    spec_dict["entry"] = {"indicator": "volume", "operator": "crossesAbove", "value": 100}
    assert only(validate_spec(spec_of(spec_dict)), SpecErrorCode.UNSUPPORTED_OPERATOR)


@pytest.mark.parametrize("indicator", ["rsi", "sma", "ema", "atr"])
def test_crossings_are_allowed_on_series_indicators(
    spec_dict: dict[str, Any], indicator: str
) -> None:
    spec_dict["entry"] = {
        "indicator": indicator,
        "period": 14,
        "operator": "crossesAbove",
        "value": 30,
    }
    assert SpecErrorCode.UNSUPPORTED_OPERATOR not in codes(validate_spec(spec_of(spec_dict)))


# --- missing operands ----------------------------------------------------


def test_a_comparison_without_a_threshold_is_rejected(spec_dict: dict[str, Any]) -> None:
    spec_dict["entry"] = {"indicator": "volume", "operator": "greaterThan"}
    error = only(validate_spec(spec_of(spec_dict)), SpecErrorCode.MISSING_THRESHOLD)
    assert error.path == "entry.value"


def test_an_sma_comparison_without_a_period_is_rejected(spec_dict: dict[str, Any]) -> None:
    spec_dict["entry"] = {"indicator": "volume", "operator": "greaterThanSma"}
    error = only(validate_spec(spec_of(spec_dict)), SpecErrorCode.MISSING_PERIOD)
    assert error.path == "entry.period"


# --- structure -----------------------------------------------------------


def test_an_empty_group_is_rejected(spec_dict: dict[str, Any]) -> None:
    # The schema lets this parse so the error arrives here with a path,
    # rather than as a schema exception that stops at the first problem.
    spec_dict["entry"] = {"all": []}
    error = only(validate_spec(spec_of(spec_dict)), SpecErrorCode.EMPTY_CONDITION_GROUP)
    assert error.path == "entry"
    assert "every bar" in error.message


def test_a_nested_empty_group_is_found(spec_dict: dict[str, Any]) -> None:
    spec_dict["entry"] = {"all": [{"any": []}]}
    assert only(validate_spec(spec_of(spec_dict)), SpecErrorCode.EMPTY_CONDITION_GROUP).path == (
        "entry.all[0]"
    )


def test_an_exit_condition_in_entry_is_rejected(spec_dict: dict[str, Any]) -> None:
    spec_dict["entry"] = {"all": [{"type": "takeProfitPercent", "value": 4}]}
    error = only(validate_spec(spec_of(spec_dict)), SpecErrorCode.EXIT_CONDITION_IN_ENTRY)
    assert error.path == "entry.all[0]"
    assert "no position yet" in error.message


def test_indicator_conditions_are_fine_in_exit(spec_dict: dict[str, Any]) -> None:
    # The documented example does exactly this.
    assert SpecErrorCode.EXIT_CONDITION_IN_ENTRY not in codes(validate_spec(spec_of(spec_dict)))


def test_a_duplicate_condition_is_reported(spec_dict: dict[str, Any]) -> None:
    leaf = {"indicator": "rsi", "period": 14, "operator": "greaterThan", "value": 70}
    spec_dict["entry"] = {"all": [leaf, dict(leaf)]}
    assert only(validate_spec(spec_of(spec_dict)), SpecErrorCode.DUPLICATE_CONDITION).path == (
        "entry.all[1]"
    )


def test_the_same_indicator_with_different_periods_is_allowed(spec_dict: dict[str, Any]) -> None:
    # An SMA crossover is two SMAs. Series identity is (indicator, period), so
    # these are genuinely different series, not a conflict.
    spec_dict["entry"] = {
        "all": [
            {"indicator": "sma", "period": 10, "operator": "greaterThan", "value": 1},
            {"indicator": "sma", "period": 50, "operator": "lessThan", "value": 1},
        ]
    }
    assert SpecErrorCode.DUPLICATE_CONDITION not in codes(validate_spec(spec_of(spec_dict)))


def test_the_same_condition_in_entry_and_exit_is_not_a_duplicate(
    spec_dict: dict[str, Any]
) -> None:
    leaf = {"indicator": "rsi", "period": 14, "operator": "greaterThan", "value": 70}
    spec_dict["entry"] = {"all": [dict(leaf)]}
    spec_dict["exit"] = {"any": [dict(leaf), {"type": "stopLossPercent", "value": 2}]}
    assert SpecErrorCode.DUPLICATE_CONDITION not in codes(validate_spec(spec_of(spec_dict)))


# --- stops ---------------------------------------------------------------


def test_risk_sizing_without_a_stop_is_rejected(spec_dict: dict[str, Any]) -> None:
    # quantity = equity x riskPercent / (entry x stopLossPercent). Without a
    # stop there is no denominator.
    spec_dict["exit"] = {"any": [{"type": "takeProfitPercent", "value": 4}]}
    error = only(validate_spec(spec_of(spec_dict)), SpecErrorCode.MISSING_STOP_LOSS)
    assert error.path == "exit"


def test_a_stop_nested_in_the_exit_tree_counts(spec_dict: dict[str, Any]) -> None:
    spec_dict["exit"] = {"any": [{"all": [{"type": "stopLossPercent", "value": 2}]}]}
    assert SpecErrorCode.MISSING_STOP_LOSS not in codes(validate_spec(spec_of(spec_dict)))


def test_a_stop_in_entry_does_not_satisfy_the_requirement(spec_dict: dict[str, Any]) -> None:
    spec_dict["entry"] = {"all": [{"type": "stopLossPercent", "value": 2}]}
    spec_dict["exit"] = {"any": [{"type": "takeProfitPercent", "value": 4}]}
    reported = codes(validate_spec(spec_of(spec_dict)))
    assert SpecErrorCode.MISSING_STOP_LOSS in reported
    assert SpecErrorCode.EXIT_CONDITION_IN_ENTRY in reported


# --- warmup --------------------------------------------------------------


def test_a_period_longer_than_the_window_is_rejected(spec_dict: dict[str, Any]) -> None:
    spec_dict["entry"] = {"indicator": "rsi", "period": 300, "operator": "greaterThan", "value": 70}
    error = only(
        validate_spec(spec_of(spec_dict), available_bars=200),
        SpecErrorCode.INDICATOR_PERIOD_TOO_LARGE,
    )
    assert error.path == "entry.period"
    assert error.limit == "200"
    assert error.observed == "300"


def test_a_period_that_fits_is_accepted(spec_dict: dict[str, Any]) -> None:
    assert validate_spec(spec_of(spec_dict), available_bars=200) == []


def test_the_derived_sma_window_is_checked_too(spec_dict: dict[str, Any]) -> None:
    # The condition's own period is the averaging window here, so the series
    # that must fit is volumeSma, not volume.
    spec_dict["entry"] = {"indicator": "volume", "operator": "greaterThanSma", "period": 500}
    error = only(
        validate_spec(spec_of(spec_dict), available_bars=200),
        SpecErrorCode.INDICATOR_PERIOD_TOO_LARGE,
    )
    assert "volumeSma" in error.message


def test_warmup_is_not_probed_for_an_unsupported_pairing(spec_dict: dict[str, Any]) -> None:
    # atr + greaterThanSma implies an `atrSma` series the registry has no entry
    # for. Probing it would make the validator raise -- a 500 where the caller
    # should get a 422 and a list.
    spec_dict["entry"] = {"indicator": "atr", "period": 500, "operator": "greaterThanSma"}
    reported = codes(validate_spec(spec_of(spec_dict), available_bars=200))
    assert SpecErrorCode.UNSUPPORTED_OPERATOR in reported


# --- catalog -------------------------------------------------------------


def test_a_symbol_missing_from_the_catalog_is_rejected(spec_dict: dict[str, Any]) -> None:
    spec_dict["market"]["symbols"] = ["DOGE/USDT"]
    error = only(
        validate_spec(spec_of(spec_dict), known_instruments={"BTCUSDT.BINANCE"}),
        SpecErrorCode.SYMBOL_NOT_IN_CATALOG,
    )
    assert error.path == "market.symbols[0]"
    assert error.observed == "DOGEUSDT.BINANCE"


def test_a_symbol_present_in_the_catalog_is_accepted(spec_dict: dict[str, Any]) -> None:
    assert validate_spec(spec_of(spec_dict), known_instruments={"BTCUSDT.BINANCE"}) == []


def test_each_missing_symbol_is_reported(spec_dict: dict[str, Any]) -> None:
    spec_dict["market"]["symbols"] = ["BTC/USDT", "DOGE/USDT", "SHIB/USDT"]
    errors = validate_spec(spec_of(spec_dict), known_instruments={"BTCUSDT.BINANCE"})
    assert [error.path for error in errors] == ["market.symbols[1]", "market.symbols[2]"]


# --- reporting behaviour -------------------------------------------------


def test_every_problem_is_reported_not_just_the_first(spec_dict: dict[str, Any]) -> None:
    # A caller fixing one field per round trip is a bad API.
    spec_dict["entry"] = {
        "all": [
            {"indicator": "atr", "period": 500, "operator": "greaterThanSma"},
            {"type": "takeProfitPercent", "value": 4},
            {"any": []},
        ]
    }
    spec_dict["exit"] = {"any": [{"indicator": "rsi", "period": 14, "operator": "greaterThan", "value": 70}]}
    spec_dict["market"]["symbols"] = ["DOGE/USDT"]

    reported = set(
        codes(
            validate_spec(
                spec_of(spec_dict), available_bars=200, known_instruments={"BTCUSDT.BINANCE"}
            )
        )
    )

    assert reported == {
        SpecErrorCode.UNSUPPORTED_OPERATOR,
        SpecErrorCode.EXIT_CONDITION_IN_ENTRY,
        SpecErrorCode.EMPTY_CONDITION_GROUP,
        SpecErrorCode.MISSING_STOP_LOSS,
        SpecErrorCode.SYMBOL_NOT_IN_CATALOG,
    }


def test_the_validator_never_raises(spec_dict: dict[str, Any]) -> None:
    spec_dict["entry"] = {"not": {"indicator": "volume", "operator": "greaterThanSma"}}
    spec_dict["exit"] = {"all": []}
    validate_spec(spec_of(spec_dict), available_bars=1, known_instruments=set())


def test_errors_are_frozen(spec_dict: dict[str, Any]) -> None:
    spec_dict["entry"] = {"all": []}
    error = validate_spec(spec_of(spec_dict))[0]
    with pytest.raises(Exception):  # noqa: B017 -- pydantic ValidationError
        error.path = "elsewhere"  # type: ignore[misc]


def test_error_codes_are_unique_and_uppercase() -> None:
    values = [code.value for code in SpecErrorCode]
    assert len(values) == len(set(values))
    assert all(value.isupper() for value in values)
