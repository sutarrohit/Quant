"""Errors raised by the live runtime.

Note what the status codes say about intent. `LiveNotPermitted` and
`ReconciliationFailed` are 409s -- the request is well formed and the service
refuses it, and no retry will change that. `CredentialUnavailable` is a 502,
because a secrets mount that is not there yet is somebody else's outage.
"""

from __future__ import annotations

from engine.errors.base import EngineError, ErrorCode


class AccountNotFound(EngineError):
    code = ErrorCode.ACCOUNT_NOT_FOUND
    http_status = 404


class CredentialUnavailable(EngineError):
    """The reference could not be resolved.

    A node must refuse to start rather than trade without credentials, and
    must say so without quoting the reference back into a log.
    """

    code = ErrorCode.CREDENTIAL_UNAVAILABLE
    http_status = 502


class LiveNotPermitted(EngineError):
    """Live trading is gated on ADR-001's conditions, none of which are met."""

    code = ErrorCode.LIVE_NOT_PERMITTED
    http_status = 409


class CacheNotIsolated(EngineError):
    """The Nautilus cache and the arq queue share a Redis instance."""

    code = ErrorCode.CACHE_NOT_ISOLATED
    http_status = 500


class MandateMissing(EngineError):
    """No mandate for an account that needs one.

    A refusal, not a warning. Absent is not permissive.
    """

    code = ErrorCode.LIVE_NOT_PERMITTED
    http_status = 409


class MandateRevoked(EngineError):
    """The mandate exists and its authority has been withdrawn."""

    code = ErrorCode.LIVE_NOT_PERMITTED
    http_status = 409


class ReconciliationFailed(EngineError):
    code = ErrorCode.RECONCILIATION_FAILED
    http_status = 409


class PreflightFailed(EngineError):
    """A dependency the control plane cannot start without."""

    code = ErrorCode.CACHE_NOT_ISOLATED
    http_status = 503
