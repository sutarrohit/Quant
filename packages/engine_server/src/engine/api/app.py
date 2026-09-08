"""FastAPI app factory.

No CORS and no static mounts: the only caller is the server-side api-control
service, not a browser (spec section 1).

Nothing here ever runs a backtest. The handler validates and enqueues; a
backtest pins a CPU for minutes and would block the event loop (spec 7.1).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from engine import __version__
from engine.api.routes import backtests, catalog, health, live
from engine.backtest.queue import ArqJobQueue
from engine.errors import EngineError, ErrorCode, status_to_code
from engine.logging import configure_logging, log_context
from engine.settings import Settings, get_settings

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    # Refuse to serve without a token rather than serve unauthenticated.
    settings.require_internal_api_key()

    @asynccontextmanager
    async def lifespan(instance: FastAPI) -> AsyncIterator[None]:
        # One Redis pool for the process. A client per request would open a
        # connection per request and exhaust the server under load.
        # redis-py ships types but leaves from_url unannotated.
        instance.state.redis = aioredis.from_url(  # type: ignore[no-untyped-call]
            settings.redis_url, decode_responses=True
        )
        instance.state.queue = await ArqJobQueue.connect(settings.redis_url)
        try:
            yield
        finally:
            await instance.state.queue.close()
            await instance.state.redis.aclose()

    app = FastAPI(
        title="NautilusTrader service",
        description="Market-data catalog, DSL strategies, and backtest jobs.",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.include_router(health.router)
    app.include_router(backtests.router)
    app.include_router(catalog.router)
    app.include_router(live.router)

    @app.middleware("http")
    async def bind_request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ) -> Any:
        # Honour a caller-supplied id so a request can be traced across services.
        request_id = request.headers.get("x-request-id") or f"req_{uuid4().hex}"
        with log_context(request_id=request_id):
            response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

    @app.exception_handler(EngineError)
    async def handle_engine_error(_: Request, exc: EngineError) -> JSONResponse:
        logger.warning("request failed", extra={"code": exc.code.value})
        return JSONResponse(status_code=exc.http_status, content=exc.to_payload())

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = status_to_code(exc.status_code)
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": code.value, "message": str(exc.detail)},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # The {"errors": [...]} shape of spec section 7.2. Step 9 replaces these
        # entries with SpecError once the DSL validator exists.
        errors = [
            {
                "path": ".".join(str(part) for part in error["loc"]),
                "code": ErrorCode.REQUEST_INVALID.value,
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"errors": errors})

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # The traceback is logged, never returned (spec section 7.4).
        logger.exception("unhandled exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"code": ErrorCode.INTERNAL.value, "message": "internal server error"},
        )

    return app


app = create_app()
