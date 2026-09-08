"""The error envelope the TypeScript caller branches on."""

from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient

from engine.api.app import create_app
from engine.errors import NotFoundError
from engine.logging import configure_logging
from tests.conftest import make_settings


def build() -> TestClient:
    app = create_app(make_settings())

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.get("/missing")
    async def missing() -> None:
        raise NotFoundError("no such job")

    @app.get("/typed/{count}")
    async def typed(count: int) -> dict[str, int]:
        return {"count": count}

    return TestClient(app, raise_server_exceptions=False)


def test_unknown_route_returns_a_code() -> None:
    response = build().get("/nope")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_engine_error_maps_to_its_status_and_code() -> None:
    response = build().get("/missing")
    assert response.status_code == 404
    assert response.json() == {"code": "NOT_FOUND", "message": "no such job"}


def test_unhandled_exception_never_leaks_a_traceback() -> None:
    # Spec section 7.4: the traceback is logged and persisted, never returned.
    response = build().get("/boom")
    assert response.status_code == 500
    assert response.json() == {"code": "INTERNAL", "message": "internal server error"}
    assert "secret internal detail" not in response.text
    assert "Traceback" not in response.text


def test_validation_error_uses_the_errors_list_shape() -> None:
    # Spec section 7.2: 422 -> {"errors": [...]}, one entry per problem.
    response = build().get("/typed/not-an-int")
    assert response.status_code == 422
    errors = response.json()["errors"]
    assert errors[0]["path"] == "path.count"
    assert errors[0]["code"] == "REQUEST_INVALID"
    assert errors[0]["message"]


def test_request_id_reaches_handler_logs() -> None:
    # The point of the middleware: a caller-supplied id must appear on records
    # emitted deep inside request handling, not just on the response header.
    client = build()
    # create_app configures root logging, so capture must be installed after it.
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    client.get("/missing", headers={"x-request-id": "req_traced"})

    engine_records = [
        json.loads(line)
        for line in stream.getvalue().splitlines()
        if json.loads(line)["logger"].startswith("engine")
    ]
    assert engine_records
    assert all(record["request_id"] == "req_traced" for record in engine_records)
