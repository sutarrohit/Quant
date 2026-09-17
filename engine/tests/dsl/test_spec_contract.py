"""Behavior tests for dsl/spec.py (FOUND-04, D-06) -- StrategySpec loading, semantic
validation, and the reproducibility hash.

Run scoped: `uv run --project engine pytest engine/tests/dsl/test_spec_contract.py -q`. Requires
`schemas/generated/ts/strategy-spec.d.ts` and `engine/generated/strategy_spec.py` to already
exist -- run `pnpm --filter @quant/schemas run build` first (Turbo's `^build` edge does this
automatically via `test`).
"""

import json
import re
from pathlib import Path

import pytest

from dsl.spec import MONEY_FIELD_NAMES, SpecLoadError, SpecSemanticError, load_spec, params_hash

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCHEMA_PATH = _REPO_ROOT / "schemas" / "strategy-spec.v1.json"
_GENERATED_TS_PATH = _REPO_ROOT / "schemas" / "generated" / "ts" / "strategy-spec.d.ts"

_MONEY_PATTERN_RE = re.compile(r"^\^-\?\[0-9\]\+")  # money field pattern always starts this way


def _valid_spec_dict() -> dict:
    return {
        "spec_version": "1",
        "symbol": "BTCUSDT",
        "bar_interval": "1h",
        "indicators": {"fast_period": 5, "slow_period": 20},
        "entry": {"rule": "fast_crosses_above_slow"},
        "exit": {"rule": "fast_crosses_below_slow"},
        "sizing": {"trade_size": "1.50000000"},
    }


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def test_valid_spec_validates(tmp_path):
    path = _write(tmp_path, "spec.json", json.dumps(_valid_spec_dict()))
    spec = load_spec(path)
    assert spec.symbol == "BTCUSDT"
    assert spec.indicators.fast_period == 5


def test_empty_file_rejected(tmp_path):
    path = _write(tmp_path, "spec.json", "")
    with pytest.raises(SpecLoadError):
        load_spec(path)


def test_empty_object_rejected(tmp_path):
    path = _write(tmp_path, "spec.json", "{}")
    with pytest.raises(SpecLoadError):
        load_spec(path)


def test_null_rejected(tmp_path):
    path = _write(tmp_path, "spec.json", "null")
    with pytest.raises(SpecLoadError):
        load_spec(path)


def test_inverted_window_rejected_semantically(tmp_path):
    data = _valid_spec_dict()
    data["indicators"] = {"fast_period": 20, "slow_period": 20}
    path = _write(tmp_path, "spec.json", json.dumps(data))
    with pytest.raises(SpecSemanticError) as excinfo:
        load_spec(path)
    assert "20" in str(excinfo.value)
    assert excinfo.value.fast_period == 20
    assert excinfo.value.slow_period == 20


def test_params_hash_unchanged_by_key_reorder(tmp_path):
    data = _valid_spec_dict()
    reordered = dict(reversed(list(data.items())))
    path_a = _write(tmp_path, "a.json", json.dumps(data))
    path_b = _write(tmp_path, "b.json", json.dumps(reordered))
    assert params_hash(load_spec(path_a)) == params_hash(load_spec(path_b))


def test_params_hash_differs_when_a_field_value_changes(tmp_path):
    data = _valid_spec_dict()
    changed = _valid_spec_dict()
    changed["indicators"]["fast_period"] = 6
    path_a = _write(tmp_path, "a.json", json.dumps(data))
    path_b = _write(tmp_path, "b.json", json.dumps(changed))
    assert params_hash(load_spec(path_a)) != params_hash(load_spec(path_b))


def test_params_hash_equal_for_differently_formatted_equal_content(tmp_path):
    data = _valid_spec_dict()
    compact = json.dumps(data, separators=(",", ":"))
    pretty = json.dumps(data, indent=4, sort_keys=True) + "\n\n"
    path_a = _write(tmp_path, "a.json", compact)
    path_b = _write(tmp_path, "b.json", pretty)
    assert params_hash(load_spec(path_a)) == params_hash(load_spec(path_b))


def test_params_hash_canonicalizes_money_precision(tmp_path):
    """`sizing.trade_size` written as "1.5" and "1.50000000" are the same money value and must
    hash identically -- the one place this hash *does* normalize representation, per D-07."""
    data = _valid_spec_dict()
    data["sizing"]["trade_size"] = "1.5"
    other = _valid_spec_dict()
    other["sizing"]["trade_size"] = "1.50000000"
    path_a = _write(tmp_path, "a.json", json.dumps(data))
    path_b = _write(tmp_path, "b.json", json.dumps(other))
    assert params_hash(load_spec(path_a)) == params_hash(load_spec(path_b))


def test_money_field_name_list_matches_schema():
    """Closes Option A's one stated weakness (ADR-0003): walk the schema for every field
    declared with the money pattern and assert the hand-maintained MONEY_FIELD_NAMES set in
    dsl/spec.py is exactly that set -- an added money field with no matching list entry fails
    this test instead of silently skipping canonicalization at hash time."""
    schema = json.loads(_SCHEMA_PATH.read_text())
    found: set[str] = set()

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                for field_name, field_schema in properties.items():
                    if (
                        isinstance(field_schema, dict)
                        and field_schema.get("type") == "string"
                        and _MONEY_PATTERN_RE.match(field_schema.get("pattern", ""))
                    ):
                        found.add(field_name)
                    _walk(field_schema)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(schema)
    assert found == set(MONEY_FIELD_NAMES)


def test_generated_ts_trade_size_is_string():
    if not _GENERATED_TS_PATH.exists():
        pytest.fail(
            f"{_GENERATED_TS_PATH} missing -- run 'pnpm --filter @quant/schemas run build' first"
        )
    ts = _GENERATED_TS_PATH.read_text()
    assert "trade_size: string;" in ts
    assert not re.search(r"trade_size\??: *number", ts)
