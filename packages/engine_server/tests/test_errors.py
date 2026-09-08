from __future__ import annotations

import pytest

from engine.errors import (
    ConfigurationError,
    EngineError,
    ErrorCode,
    NotFoundError,
    NotReadyError,
    UnauthenticatedError,
    status_to_code,
)


def test_payload_carries_a_stable_code() -> None:
    payload = NotFoundError("no such job").to_payload()
    assert payload == {"code": "NOT_FOUND", "message": "no such job"}


def test_payload_includes_details_when_given() -> None:
    payload = NotReadyError("not ready", details={"checks": {"catalog": "missing"}}).to_payload()
    assert payload["details"] == {"checks": {"catalog": "missing"}}


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (NotFoundError, 404),
        (UnauthenticatedError, 401),
        (NotReadyError, 503),
        (ConfigurationError, 500),
    ],
)
def test_http_status_per_error(error: type[EngineError], status: int) -> None:
    assert error.http_status == status


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, ErrorCode.UNAUTHENTICATED),
        (404, ErrorCode.NOT_FOUND),
        (503, ErrorCode.NOT_READY),
        (409, ErrorCode.REQUEST_INVALID),
        (500, ErrorCode.INTERNAL),
    ],
)
def test_status_to_code(status: int, code: ErrorCode) -> None:
    assert status_to_code(status) is code


def test_codes_are_unique_and_uppercase() -> None:
    # Codes are API contract (spec section 12): the TypeScript caller branches on
    # them, so a duplicate or a renamed value silently breaks a branch there.
    values = [member.value for member in ErrorCode]
    assert len(values) == len(set(values))
    assert all(value.isupper() for value in values)
