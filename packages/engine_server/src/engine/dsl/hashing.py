"""Canonical serialization and hashing of strategy specs.

The hash is an identity, not a checksum: ``api-control`` derives
``strategyVersionId`` from it, stores results against it, and uses it to decide
whether a spec has already been backtested. Two things follow.

**It must be stable across processes.** No dict ordering, no locale, no
``PYTHONHASHSEED`` dependence. Sorted keys, fixed separators, ASCII-escaped
output.

**Equivalent specs must hash equally.** ``30``, ``30.0``, ``30.00`` and
``3E+1`` are one RSI threshold, but Pydantic preserves each as written and they
serialize to four different strings. Without normalization the same strategy
re-submitted with a trailing zero looks like a new version and re-runs a
backtest that already exists. Numbers are therefore emitted in a single
canonical form.

**Absent optional fields must not appear.** Adding an optional field to the
schema would otherwise change the hash of every spec ever written, because a
new ``"reference": null`` would appear in each one -- and every stored result
would point at an identity nobody could reproduce. Omitting ``None`` makes a
field that was never set indistinguishable from a field that did not exist,
which is the only way the identity survives the schema growing. It is also
semantically right: ``value: null`` and no ``value`` mean the same thing.

This is **not** the wire format. API responses use
``model_dump(mode="json")``; this exists solely to be hashed.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from engine.dsl.schema import StrategySpec


def canonical_number(value: Decimal) -> str:
    """The one spelling of a number.

    ``normalize()`` strips trailing zeros but can produce exponent notation
    (``Decimal("30.0").normalize()`` is ``3E+1``), so the result is formatted
    fixed-point.
    """
    if not value.is_finite():
        raise ValueError(f"spec numbers must be finite, got {value}")
    return format(value.normalize(), "f")


def _encode(value: Any) -> str:
    if isinstance(value, Decimal):
        return canonical_number(value)
    raise TypeError(f"cannot canonicalise {type(value).__name__}")


def canonical_json(spec: StrategySpec) -> str:
    """The exact bytes that get hashed.

    Dumped in ``python`` mode so ``Decimal`` values survive as ``Decimal`` and
    reach ``canonical_number``; ``mode="json"`` would have already frozen them
    as whatever string they were written with.
    """
    payload = spec.model_dump(mode="python", by_alias=True, exclude_none=True)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=_encode,
    )


def spec_hash(spec: StrategySpec) -> str:
    """SHA-256 of the canonical form, lowercase hex."""
    return hashlib.sha256(canonical_json(spec).encode("utf-8")).hexdigest()
