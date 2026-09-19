"""Errors raised by the job store.

All three are races or misuse around the same compare-and-set: two submissions
sharing a request id, a job that expired, a cancel that lost to the worker.
"""

from __future__ import annotations

from engine.errors.base import EngineError, ErrorCode


class RequestIdConflict(EngineError):
    """The same requestId was submitted with a different payload."""

    code = ErrorCode.REQUEST_ID_CONFLICT
    http_status = 409


class JobNotFound(EngineError):
    code = ErrorCode.JOB_NOT_FOUND
    http_status = 404


class JobNotCancellable(EngineError):
    """Already running or finished. Cancelling would be a lie."""

    code = ErrorCode.JOB_NOT_CANCELLABLE
    http_status = 409
