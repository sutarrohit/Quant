"""Errors raised while wiring up the one strategy class.

`DslStrategy` itself contains no `except` at all (rule 9): an unknown indicator
or a bad operator raises, because a broad `except` returning `False` turns a
broken strategy into a silently inert one that reports zero return as though it
were an answer.
"""

from __future__ import annotations

from engine.errors.base import EngineError, ErrorCode


class StrategySetupError(EngineError):
    code = ErrorCode.REQUEST_INVALID
    http_status = 422
