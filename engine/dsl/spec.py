"""StrategySpec loading, semantic validation, and canonical hashing (D-02, D-06, FOUND-04).

Shape validation is delegated entirely to the generated Pydantic model
(`generated.strategy_spec.StrategySpec`, produced from `schemas/strategy-spec.v1.json` by
`schemas/scripts/generate.mjs`) -- this module never hand-declares a spec field. The one rule
the schema itself cannot express -- `fast_period` strictly less than `slow_period` -- is a
**semantic** validation performed here, after shape validation, not a schema constraint: draft
2020-12 has no portable keyword comparing one property's value against another's. `load_spec`
raises `SpecSemanticError` for that rule and `SpecLoadError` for everything shape-related,
because Phase 2's DSL-02 grows this exact seam and a semantic failure surfacing as a generic
validation error would have to be re-separated then.

This module imports only the generated model, `money`, and the standard library.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from generated.strategy_spec import StrategySpec
from money import to_canonical_str


class SpecLoadError(Exception):
    """A spec file is empty, not valid JSON, `{}`, `null`, or fails shape validation."""


class SpecSemanticError(Exception):
    """A spec is shape-valid but violates a semantic rule the schema cannot express."""

    def __init__(self, message: str, *, fast_period: int, slow_period: int) -> None:
        super().__init__(message)
        self.fast_period = fast_period
        self.slow_period = slow_period


def load_spec(path: str | Path) -> StrategySpec:
    """Read, JSON-parse, shape-validate, and semantically validate a StrategySpec file.

    Raises `SpecLoadError` for an empty file, `{}`, `null`, invalid JSON, or a shape mismatch --
    never returns `None` or a default spec for any of those. Raises `SpecSemanticError` naming
    both window fields when `fast_period >= slow_period`.
    """
    raw = Path(path).read_text()
    try:
        data = json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError as exc:
        raise SpecLoadError(f"{path}: not valid JSON") from exc

    if data is None or data == {}:
        raise SpecLoadError(
            f"{path}: spec is empty, {{}}, or null -- a StrategySpec must declare every required field"
        )

    try:
        spec = StrategySpec.model_validate(data)
    except ValidationError as exc:
        raise SpecLoadError(f"{path}: failed schema validation: {exc}") from exc

    fast = spec.indicators.fast_period
    slow = spec.indicators.slow_period
    if fast >= slow:
        raise SpecSemanticError(
            f"fast_period ({fast}) must be strictly less than slow_period ({slow}) -- "
            "a crossover between a window and itself (or an inverted pair) has no defined semantics",
            fast_period=fast,
            slow_period=slow,
        )
    return spec


# The money-field name list this schema declares (D-07 pattern-typed string fields). Hand
# maintained per ADR-0003's Option A -- `test_money_field_name_list_matches_schema` walks
# `schemas/strategy-spec.v1.json` and asserts this set is exactly the schema's money-patterned
# field names, so an added money field with no corresponding entry here fails the build instead
# of silently skipping canonicalization at hash time.
MONEY_FIELD_NAMES = frozenset({"trade_size"})


def params_hash(spec: StrategySpec) -> str:
    """SHA-256 hex digest over the canonical serialization: sorted keys, no whitespace, money
    values as their canonical decimal strings via `money.to_canonical_str`.
    """
    canonical = _canonicalize(spec.model_dump(mode="json"))
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonicalize(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: (to_canonical_str(val) if key in MONEY_FIELD_NAMES else _canonicalize(val))
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    return value


__all__ = [
    "StrategySpec",
    "SpecLoadError",
    "SpecSemanticError",
    "MONEY_FIELD_NAMES",
    "load_spec",
    "params_hash",
]
