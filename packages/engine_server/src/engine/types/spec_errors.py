"""How a spec is rejected (spec section 7.2).

A list, not a first failure: the caller shows every problem at once, each
tagged with the path it sits on.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class SpecErrorCode(StrEnum):
    """Codes the TypeScript caller branches on. Values are never renamed."""

    UNKNOWN_INDICATOR = "UNKNOWN_INDICATOR"
    UNSUPPORTED_OPERATOR = "UNSUPPORTED_OPERATOR"
    INDICATOR_PERIOD_TOO_LARGE = "INDICATOR_PERIOD_TOO_LARGE"
    EMPTY_CONDITION_GROUP = "EMPTY_CONDITION_GROUP"
    MISSING_STOP_LOSS = "MISSING_STOP_LOSS"
    SYMBOL_NOT_IN_CATALOG = "SYMBOL_NOT_IN_CATALOG"
    EXIT_CONDITION_IN_ENTRY = "EXIT_CONDITION_IN_ENTRY"
    MISSING_THRESHOLD = "MISSING_THRESHOLD"
    MISSING_PERIOD = "MISSING_PERIOD"
    AMBIGUOUS_COMPARISON = "AMBIGUOUS_COMPARISON"
    INVALID_REFERENCE = "INVALID_REFERENCE"
    DUPLICATE_CONDITION = "DUPLICATE_CONDITION"


class SpecError(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    code: SpecErrorCode
    message: str
    limit: str | None = None
    observed: str | None = None
