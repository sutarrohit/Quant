"""Structured JSON logging (spec section 12).

Context fields -- ``job_id``, ``strategy_version_id``, ``spec_hash``,
``request_id`` -- are bound with ``log_context`` and appear on every record
emitted inside that block, so call sites do not have to thread them through.

Spec bodies are logged at DEBUG only; they get large.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import IO, Any

# Default is None, not {}: a mutable default on a ContextVar is shared across
# every context that never calls .set().
_log_context: ContextVar[dict[str, Any] | None] = ContextVar("engine_log_context", default=None)

# Attributes every LogRecord carries. Anything else in a record's __dict__ came
# from `extra=` at the call site and belongs in the payload.
_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "asctime",
    "message",
    "taskName",
}


def get_context() -> dict[str, Any]:
    return dict(_log_context.get() or {})


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """Bind fields onto every log record emitted inside the block."""
    token = _log_context.set({**get_context(), **fields})
    try:
        yield
    finally:
        _log_context.reset(token)


#: Fields whose *value* never appears in a log, whatever it is.
#:
#: ADR-001 requires that a key never reach a log, an exception, a job record or
#: an HTTP response. `VenueCredentials.__repr__` covers the object; this covers
#: the field, for the case where something passes the string itself -- which is
#: the mistake that actually happens, usually in a debug line written at 2am
#: and never removed.
#:
#: Matched on the field name, case-insensitively, by substring: `api_key`,
#: `apiKey`, `binance_api_secret` and `token` all redact. Over-redacting a log
#: line costs nothing; under-redacting one costs a key.
SECRET_FIELD_MARKERS = ("secret", "api_key", "apikey", "password", "passphrase", "token")

REDACTED = "***"


def _is_secret(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in SECRET_FIELD_MARKERS)


def redact(fields: dict[str, Any]) -> dict[str, Any]:
    """Replace the value of anything that looks like a secret.

    Deliberately blunt and name-based. A value-based check -- "does this look
    like a key" -- cannot be right: an API key is an opaque string and so is
    half of everything else that is logged.
    """
    return {
        key: (REDACTED if _is_secret(key) else value) for key, value in fields.items()
    }


class JsonFormatter(logging.Formatter):
    """One JSON object per line.

    Keys are sorted so log output is diffable and stable across runs, and any
    field that names a secret has its value replaced before it is written.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(redact(get_context()))
        # Per-call `extra=` wins over ambient context.
        payload.update(
            redact({k: v for k, v in record.__dict__.items() if k not in _RESERVED})
        )
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, sort_keys=True)


def configure_logging(level: str = "INFO", *, stream: IO[str] | None = None) -> None:
    """Install the JSON formatter on the root logger. Idempotent."""
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    # Let uvicorn's records reach our formatter instead of its own.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
