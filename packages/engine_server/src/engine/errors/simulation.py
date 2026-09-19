"""Errors raised by the simulated-execution runtime."""

from __future__ import annotations

from engine.errors.base import EngineError, ErrorCode


class VenueNotSupported(EngineError):
    """No adapter for this venue.

    Raised rather than logged. Nautilus's own behaviour here is to log at ERROR
    and carry on, which produces a node that trades nothing and reports itself
    healthy -- the exact failure this module exists to prevent.
    """

    code = ErrorCode.REQUEST_INVALID
    http_status = 422
