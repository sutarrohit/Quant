from __future__ import annotations

import copy
import json
import subprocess
import sys
import textwrap
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from engine.dsl.hashing import canonical_json, canonical_number, spec_hash
from engine.dsl.schema import StrategySpec
from tests.dsl.conftest import SPEC_EXAMPLE


def spec_of(payload: dict[str, Any]) -> StrategySpec:
    return StrategySpec.model_validate(payload)


# --- round trip ----------------------------------------------------------


def test_round_trip_is_identical(spec_dict: dict[str, Any]) -> None:
    spec = spec_of(spec_dict)
    again = StrategySpec.model_validate(spec.model_dump(mode="json", by_alias=True))
    assert again == spec
    assert canonical_json(again) == canonical_json(spec)
    assert spec_hash(again) == spec_hash(spec)


def test_round_trip_survives_python_side_names(spec_dict: dict[str, Any]) -> None:
    # Dumping without aliases produces all_/exit_; re-validating must still work
    # or a spec could not be passed around inside the process.
    spec = spec_of(spec_dict)
    assert StrategySpec.model_validate(spec.model_dump(mode="python")) == spec


# --- canonical numbers ---------------------------------------------------


@pytest.mark.parametrize(
    ("written", "canonical"),
    [
        ("30", "30"),
        ("30.0", "30"),
        ("30.00", "30"),
        ("3E+1", "30"),
        ("0.100", "0.1"),
        ("1.5", "1.5"),
        ("100", "100"),
        ("0.0001", "0.0001"),
        ("-2.50", "-2.5"),
    ],
)
def test_canonical_number(written: str, canonical: str) -> None:
    assert canonical_number(Decimal(written)) == canonical


def test_canonical_number_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="must be finite"):
        canonical_number(Decimal("NaN"))


@pytest.mark.parametrize("written", [30, 30.0, "30.00", "3E+1"])
def test_equivalent_thresholds_hash_equally(spec_dict: dict[str, Any], written: Any) -> None:
    # Without this, re-submitting the same strategy with a trailing zero looks
    # like a new version and re-runs a backtest that already exists.
    baseline = spec_hash(spec_of(spec_dict))
    spec_dict["entry"]["all"][0]["value"] = written
    assert spec_hash(spec_of(spec_dict)) == baseline


# --- the hash discriminates ---------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda d: d.__setitem__("version", 5), id="version"),
        pytest.param(lambda d: d.__setitem__("strategyId", "other"), id="strategy_id"),
        pytest.param(lambda d: d["market"].__setitem__("timeframe", "1h"), id="timeframe"),
        pytest.param(lambda d: d["entry"]["all"][0].__setitem__("period", 15), id="period"),
        pytest.param(lambda d: d["entry"]["all"][0].__setitem__("value", 31), id="threshold"),
        pytest.param(lambda d: d["sizing"].__setitem__("riskPercent", 2), id="sizing"),
        pytest.param(lambda d: d["entry"]["all"].pop(), id="fewer_conditions"),
    ],
)
def test_any_meaningful_change_changes_the_hash(
    spec_dict: dict[str, Any], mutate: Any
) -> None:
    baseline = spec_hash(spec_of(spec_dict))
    mutate(spec_dict)
    assert spec_hash(spec_of(spec_dict)) != baseline


def test_condition_order_is_significant(spec_dict: dict[str, Any]) -> None:
    # `all` is commutative in meaning, but the spec is stored as written and
    # the hash identifies the document, not an equivalence class.
    baseline = spec_hash(spec_of(spec_dict))
    spec_dict["entry"]["all"].reverse()
    assert spec_hash(spec_of(spec_dict)) != baseline


def test_key_order_in_the_input_is_not_significant(spec_dict: dict[str, Any]) -> None:
    baseline = spec_hash(spec_of(spec_dict))
    shuffled = dict(reversed(list(spec_dict.items())))
    shuffled["market"] = dict(reversed(list(spec_dict["market"].items())))
    assert spec_hash(spec_of(shuffled)) == baseline


# --- canonical form ------------------------------------------------------


def test_canonical_json_is_sorted_and_compact(spec_dict: dict[str, Any]) -> None:
    text = canonical_json(spec_of(spec_dict))
    assert text == json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))
    assert " " not in text.replace("BTC/USDT", "")


def test_canonical_json_uses_wire_names(spec_dict: dict[str, Any]) -> None:
    document = json.loads(canonical_json(spec_of(spec_dict)))
    assert set(document) == {"strategyId", "version", "market", "entry", "exit", "sizing"}
    assert "all" in document["entry"]


def test_canonical_json_escapes_non_ascii(spec_dict: dict[str, Any]) -> None:
    # strategyId is pattern-restricted to ASCII, but symbols are free text.
    # Escaping keeps the hashed bytes identical however the JSON is encoded
    # downstream.
    spec_dict["market"]["symbols"] = ["BTC/USDT", "ETH/EURO€"]
    text = canonical_json(spec_of(spec_dict))
    assert text.isascii()
    assert "\\u20ac" in text
    assert len(spec_hash(spec_of(spec_dict))) == 64


def test_strategy_id_is_ascii_only(spec_dict: dict[str, Any]) -> None:
    spec_dict["strategyId"] = "btc-café"
    with pytest.raises(ValidationError):
        spec_of(spec_dict)


def test_hash_is_lowercase_hex(spec_dict: dict[str, Any]) -> None:
    digest = spec_hash(spec_of(spec_dict))
    assert len(digest) == 64
    assert digest == digest.lower()
    int(digest, 16)


# --- stability across processes -----------------------------------------


def _hash_in_subprocess(payload: dict[str, Any], seed: str) -> str:
    """Hash the spec in a fresh interpreter with a given PYTHONHASHSEED."""
    script = textwrap.dedent(
        """
        import json, sys
        from engine.dsl.hashing import spec_hash
        from engine.dsl.schema import StrategySpec
        print(spec_hash(StrategySpec.model_validate(json.loads(sys.argv[1]))))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps(payload)],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
    )
    return result.stdout.strip()


def test_hash_is_stable_across_processes() -> None:
    # PYTHONHASHSEED randomises str hashing and therefore dict iteration order.
    # This is the thing the canonical form exists to be immune to, and it can
    # only be tested from separate interpreters.
    payload = copy.deepcopy(SPEC_EXAMPLE)
    first = _hash_in_subprocess(payload, "0")
    second = _hash_in_subprocess(payload, "12345")
    third = spec_hash(spec_of(payload))

    assert first == second == third, f"{first} / {second} / {third}"


def test_an_absent_optional_field_does_not_change_the_hash(spec_dict: dict[str, Any]) -> None:
    """Schema growth must not invalidate every existing identity.

    Adding an optional field once changed the hash of every spec ever written,
    because a new ``"reference": null`` appeared in each one -- and every stored
    result then pointed at an identity nobody could reproduce.
    """
    baseline = spec_hash(spec_of(spec_dict))

    # Stating the field explicitly as null must be the same as omitting it:
    # both mean "no reference".
    spec_dict["entry"]["all"][0]["reference"] = None
    assert spec_hash(spec_of(spec_dict)) == baseline


def test_null_and_absent_are_the_same_spec(spec_dict: dict[str, Any]) -> None:
    explicit = copy.deepcopy(spec_dict)
    explicit["entry"]["all"][0]["value"] = 30
    explicit["entry"]["all"][0]["reference"] = None
    assert spec_hash(spec_of(explicit)) == spec_hash(spec_of(spec_dict))


def test_canonical_json_omits_absent_fields(spec_dict: dict[str, Any]) -> None:
    text = canonical_json(spec_of(spec_dict))
    assert "null" not in text
    assert "reference" not in text


def test_a_field_that_is_set_still_changes_the_hash(spec_dict: dict[str, Any]) -> None:
    # Omitting None must not omit meaning: a reference that IS given is part
    # of the strategy's identity.
    baseline = spec_hash(spec_of(spec_dict))
    spec_dict["entry"]["all"][0] = {
        "indicator": "sma",
        "period": 10,
        "operator": "crossesAbove",
        "reference": {"indicator": "sma", "period": 50},
    }
    assert spec_hash(spec_of(spec_dict)) != baseline
