"""Errors raised while reading a strategy spec.

These are failures of the *spec as data* -- a key the interpreter was never
given, an indicator nobody registered. Semantic problems a user should fix are
not exceptions at all: the validator returns a list of `SpecError`, so every
problem is reported at once (see `engine.dsl.validator`).
"""

from __future__ import annotations

from engine.errors.base import EngineError, ErrorCode


class InterpreterError(EngineError):
    code = ErrorCode.REQUEST_INVALID
    http_status = 422


class UnknownIndicatorError(EngineError):
    """Raised, never swallowed (spec section 5.3, rule 9)."""

    code = ErrorCode.REQUEST_INVALID
    http_status = 422
