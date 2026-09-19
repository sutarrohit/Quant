"""Domain errors.

Every failure carries a stable, machine-readable ``code``. The TypeScript caller
branches on codes, never on message text (spec section 12), so a code is part of
the API contract: rename one and you break the caller.

Two response shapes, both defined here:

* single error   ``{"code": "...", "message": "...", "details": {...}}``
* validation     ``{"errors": [{"path": ..., "code": ..., "message": ...}, ...]}``

The second matches ``SpecError`` from spec section 5.2, which the DSL validator
returns in Step 9. Validation reports every problem at once, hence a list.

Tracebacks never appear in either shape. They are logged and persisted to the
job record; the caller gets a code and a short message (spec section 7.4).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, ClassVar


class ErrorCode(StrEnum):
    """Stable error codes.

    Phases append to this enum; values are never renamed or reused. Codes for a
    feature land in the step that builds it, so this stays short until Phase 3.
    """

    INTERNAL = "INTERNAL"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    NOT_READY = "NOT_READY"
    CONFIGURATION_INVALID = "CONFIGURATION_INVALID"
    REQUEST_INVALID = "REQUEST_INVALID"
    CATALOG_INVALID = "CATALOG_INVALID"
    INSTRUMENT_INVALID = "INSTRUMENT_INVALID"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    UPSTREAM_RATE_LIMITED = "UPSTREAM_RATE_LIMITED"
    UPSTREAM_RESPONSE_INVALID = "UPSTREAM_RESPONSE_INVALID"
    TIMESTAMP_DISCIPLINE = "TIMESTAMP_DISCIPLINE"
    DATA_QUALITY = "DATA_QUALITY"
    REQUEST_ID_CONFLICT = "REQUEST_ID_CONFLICT"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    JOB_NOT_CANCELLABLE = "JOB_NOT_CANCELLABLE"
    TIMEOUT = "TIMEOUT"
    BACKTEST_FAILED = "BACKTEST_FAILED"
    NO_DATA_FOR_WINDOW = "NO_DATA_FOR_WINDOW"
    SYMBOL_UNKNOWN_AT_VENUE = "SYMBOL_UNKNOWN_AT_VENUE"
    VENUE_UNSUPPORTED = "VENUE_UNSUPPORTED"
    DATA_RANGE_UNAVAILABLE = "DATA_RANGE_UNAVAILABLE"
    BACKTEST_INCOMPLETE = "BACKTEST_INCOMPLETE"
    ACCOUNT_NOT_FOUND = "ACCOUNT_NOT_FOUND"
    CREDENTIAL_UNAVAILABLE = "CREDENTIAL_UNAVAILABLE"
    LEASE_HELD = "LEASE_HELD"
    LIVE_NOT_PERMITTED = "LIVE_NOT_PERMITTED"
    CACHE_NOT_ISOLATED = "CACHE_NOT_ISOLATED"
    RECONCILIATION_FAILED = "RECONCILIATION_FAILED"


class EngineError(Exception):
    """Base for expected, recoverable failures."""

    code: ClassVar[ErrorCode] = ErrorCode.INTERNAL
    http_status: ClassVar[int] = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code.value, "message": self.message}
        if self.details is not None:
            payload["details"] = self.details
        return payload


class SpecInvalid(EngineError):
    """Semantic validation failed. Carries every problem, not the first.

    Renders as ``{"errors": [...]}`` rather than the single-error envelope,
    because spec section 7.2 fixes that shape for a 422 and the caller shows
    the whole list to a user.
    """

    code = ErrorCode.REQUEST_INVALID
    http_status = 422

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__("the strategy spec is not runnable")
        self.errors = errors

    def to_payload(self) -> dict[str, Any]:
        return {"errors": self.errors}


class NotFoundError(EngineError):
    code = ErrorCode.NOT_FOUND
    http_status = 404


class UnauthenticatedError(EngineError):
    code = ErrorCode.UNAUTHENTICATED
    http_status = 401


class NotReadyError(EngineError):
    """A dependency the service needs is not usable yet. Drives ``GET /ready``."""

    code = ErrorCode.NOT_READY
    http_status = 503


class ConfigurationError(EngineError):
    """Misconfiguration found at startup. Never returned to a caller."""

    code = ErrorCode.CONFIGURATION_INVALID
    http_status = 500


def status_to_code(http_status: int) -> ErrorCode:
    """Map an HTTP status raised outside our own exceptions onto a stable code."""
    match http_status:
        case 401:
            return ErrorCode.UNAUTHENTICATED
        case 404:
            return ErrorCode.NOT_FOUND
        case 503:
            return ErrorCode.NOT_READY
        case status if 400 <= status < 500:
            return ErrorCode.REQUEST_INVALID
        case _:
            return ErrorCode.INTERNAL
