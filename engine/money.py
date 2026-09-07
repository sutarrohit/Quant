"""The money boundary: strict Decimal internally, decimal-string wire format at the edges.

Money enters this system from JSON, from a spec file, or from a CSV row as a decimal *string*
(never a JSON number, per D-07 -- a JS float is exactly what that decision forbids). This module
keeps two contracts distinct and tests them separately, because one strict model cannot hold both:

- **Wire** -- ``parse_money()`` is the only sanctioned route from a decimal string (or an
  existing ``Decimal``, idempotently) into a ``Decimal``. It is not built on Pydantic's JSON-mode
  validation entry point, or on any assumption about which input types strict mode permits in
  JSON mode -- that conversion table is a version-dependent detail of the library, and pinning
  this project's money contract to it would make a Pydantic upgrade a correctness event.
  ``parse_money`` is a dozen lines this project owns and can test.
- **Internal** -- once a value is inside the system it is a ``Decimal`` and nothing else.
  ``Money``'s ``strict=True`` config is what enforces that: it rejects a plain string in Python
  mode. That rejection is the contract working, not a bug to route around -- it is what stops a
  later "just accept a string too, for convenience" change from quietly deleting the boundary.

``MONEY_SCALE`` matches the schema pattern's maximum decimal places
(``schemas/strategy-spec.v1.json``, ``^-?[0-9]+(\\.[0-9]{1,8})?$``). Rounding is always explicit
(``ROUND_HALF_EVEN``, never the ambient decimal context, which is process-global mutable state
whose rounding a value would otherwise depend on whatever else ran first in the process) and
``float()`` never appears on any money path in this module.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict

MONEY_SCALE = 8

_MONEY_PATTERN = re.compile(r"^-?[0-9]+(\.[0-9]{1,8})?$")

_QUANTUM = Decimal(1).scaleb(-MONEY_SCALE)


class Money(BaseModel):
    """The internal contract: a monetary amount is a ``Decimal``, strictly, or nothing at all."""

    model_config = ConfigDict(strict=True)

    amount: Decimal


def parse_money(value: object) -> Decimal:
    """The one sanctioned wire-to-internal conversion.

    Accepts a decimal string matching the schema's money pattern, or an existing ``Decimal``
    (idempotently). Raises on everything else, including a ``float``, an empty string, and
    ``None`` -- none of those is silently coerced to ``Decimal('0')``.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        if not _MONEY_PATTERN.match(value):
            raise ValueError(f"not a valid money string (max {MONEY_SCALE} decimal places): {value!r}")
        try:
            return Decimal(value)
        except InvalidOperation as exc:  # pragma: no cover - pattern already excludes this
            raise ValueError(f"not a valid decimal string: {value!r}") from exc
    raise TypeError(f"money value must be a decimal string or Decimal, got {type(value).__name__}: {value!r}")


def to_canonical_str(value: Decimal | str) -> str:
    """The one canonical decimal-string form used by every hash input.

    Quantizes to ``MONEY_SCALE`` places with explicit banker's rounding, then normalizes so
    ``Decimal('1.50')`` and ``Decimal('1.5')`` produce the identical canonical string. Fixed-point
    (never exponential) notation, so the form is stable regardless of how the value arrived.
    """
    amount = parse_money(value) if isinstance(value, str) else value
    quantized = amount.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)
    return format(quantized.normalize(), "f")


def assert_no_floats(obj: object, *, _path: str = "$") -> None:
    """Recursively walk a nested dict/list/tuple structure, raising and naming the path where a
    ``float`` was found.

    Guards the specific leak this project's research found: one upstream engine's position
    field serializes as a raw float while every other money-shaped field the engine emits is a
    decimal string, and the engine's own report generator deletes that column before returning.
    Any persistence path in this project goes through the engine's report generators for the same
    reason; this walker is what makes a regression there loud instead of silent.
    """
    if isinstance(obj, float):
        raise TypeError(f"float found at {_path} -- money values must be Decimal or decimal strings, never float")
    if isinstance(obj, dict):
        for key, val in obj.items():
            assert_no_floats(val, _path=f"{_path}.{key}")
    elif isinstance(obj, (list, tuple)):
        for i, val in enumerate(obj):
            assert_no_floats(val, _path=f"{_path}[{i}]")
