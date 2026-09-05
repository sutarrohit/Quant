from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import settings
from db.database import Base, engine
from exceptions import ServiceError
from routers import posts, users


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup
    # Schema is owned by Alembic; create_all is a convenience for local dev only.
    if settings.is_development:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown
    await engine.dispose()


app = FastAPI(
    title="FastAPI Blog",
    description="Template blog API with JWT auth, async SQLAlchemy and pagination.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS - allows the web frontend to call this API from another origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(posts.router, prefix="/api/posts", tags=["posts"])


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok", "environment": settings.environment}


# Uploaded media. The directory is resolved from settings so the server can be
# started from any working directory.
settings.media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")


# --------------------- ERROR ROUTES -------------------------

# Default Error
@app.get("/error", include_in_schema=False)
def throw_error():
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Default error route")


# Domain errors raised by the service layer map onto the same envelope
@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exception: ServiceError):
    headers = {"WWW-Authenticate": "Bearer"} if exception.status_code == status.HTTP_401_UNAUTHORIZED else None

    return JSONResponse(
        status_code=exception.status_code,
        content={
            "status": exception.status_code,
            "message": exception.message,
            "path": str(request.url),
        },
        headers=headers,
    )


# Global Error Handler
@app.exception_handler(StarletteHTTPException)
async def general_http_exception_handler(request: Request, exception: StarletteHTTPException):
    return JSONResponse(
        status_code=exception.status_code,
        content={
            "status": exception.status_code,
            "message": exception.detail,
            "path": str(request.url),
        },
    )


# Validation Error Handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exception: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "status": status.HTTP_422_UNPROCESSABLE_CONTENT,
            "message": "Validation error",
            "errors": jsonable_encoder(exception.errors()),
        },
    )
