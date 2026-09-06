"""Fixtures for engine/tests/persistence.

Require a live Postgres reachable via DATABASE_URL, defaulting to the local compose instance
(docker-compose.yml, D-10) when the environment does not already set one — so
`uv run --project engine pytest engine/tests/persistence -q` works with no extra setup once
`docker compose up -d postgres` has run.
"""

import os

import pytest
import sqlalchemy as sa

from persistence.db import engine_from_env

os.environ.setdefault("DATABASE_URL", "postgresql://quant:quant@localhost:5432/quant")


@pytest.fixture(scope="session")
def db_engine():
    engine = engine_from_env()
    yield engine
    engine.dispose()


@pytest.fixture
def conn(db_engine):
    with db_engine.connect() as connection:
        yield connection


@pytest.fixture(autouse=True)
def _clean_tables(db_engine):
    # Deletes are scoped to child-then-parent order so the FK from symbol_listing_snapshot to
    # snapshot_capture never blocks cleanup between tests.
    from persistence.snapshots import snapshot_capture, symbol_listing_snapshot
    from persistence.trials import trials

    yield
    with db_engine.begin() as connection:
        connection.execute(sa.delete(symbol_listing_snapshot))
        connection.execute(sa.delete(snapshot_capture))
        connection.execute(sa.delete(trials))
