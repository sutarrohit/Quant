"""Database connection helpers for engine/persistence (D-11).

`engine_from_env()` and `session_scope()` are the sole entry points into Postgres from this
codebase; nothing else in `engine/` should call `sqlalchemy.create_engine` directly. Every write
into a Prisma-migrated table goes through the Core Table mirrors in
`engine/persistence/trials.py` and `engine/persistence/snapshots.py` — this module only owns the
connection.
"""

import contextlib
import os
from collections.abc import Generator

import sqlalchemy as sa


def engine_from_env() -> sa.Engine:
    """Build a SQLAlchemy Engine from the DATABASE_URL environment variable.

    `DATABASE_URL` (shared with Prisma via `prisma/.env`) uses the plain `postgresql://` scheme,
    but this project's Python dependency is `psycopg` (v3), not the SQLAlchemy-default
    `psycopg2` — so a bare `postgresql://` URL is rewritten to `postgresql+psycopg://` here
    rather than requiring two different DATABASE_URL values for the two toolchains.
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to connect to Postgres (see prisma/.env.example)")
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return sa.create_engine(database_url)


@contextlib.contextmanager
def session_scope(engine: sa.Engine | None = None) -> Generator[sa.Connection]:
    """Yield a Connection bound to one transaction: commits on normal exit, rolls back on
    exception. Pass an existing `Engine` to reuse its connection pool; otherwise a disposable one
    is built from `DATABASE_URL` and disposed on exit."""
    owns_engine = engine is None
    engine = engine or engine_from_env()
    try:
        with engine.connect() as conn, conn.begin():
            yield conn
    finally:
        if owns_engine:
            engine.dispose()
