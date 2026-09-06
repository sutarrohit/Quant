"""Two-way column-name parity between the hand-declared Core Table mirrors and the live
Prisma-migrated database (behavior 7).

Compared in both directions: a physical column with no Core mirror, and a Core column with no
physical counterpart, must both fail. The second direction is the one that catches a Prisma
field added without its `@map` — the Core side would carry `strategy_lineage_id` while the
database still carries `strategyLineageId`, and only a two-way comparison sees that.
"""

import sqlalchemy as sa

from persistence.snapshots import snapshot_capture, symbol_listing_snapshot
from persistence.trials import trials

_TABLES = {
    "trials": trials,
    "snapshot_capture": snapshot_capture,
    "symbol_listing_snapshot": symbol_listing_snapshot,
}


def _physical_columns(conn, table_name: str) -> set[str]:
    result = conn.execute(
        sa.text("SELECT column_name FROM information_schema.columns WHERE table_name = :table_name"),
        {"table_name": table_name},
    )
    return {row[0] for row in result}


def test_trials_columns_match_physical_columns(conn):
    _assert_parity(conn, "trials")


def test_snapshot_capture_columns_match_physical_columns(conn):
    _assert_parity(conn, "snapshot_capture")


def test_symbol_listing_snapshot_columns_match_physical_columns(conn):
    _assert_parity(conn, "symbol_listing_snapshot")


def _assert_parity(conn, table_name: str) -> None:
    core_columns = set(_TABLES[table_name].columns.keys())
    physical_columns = _physical_columns(conn, table_name)

    missing_from_core = physical_columns - core_columns
    missing_from_db = core_columns - physical_columns

    assert not missing_from_core, f"{table_name}: physical columns with no Core mirror: {missing_from_core}"
    assert not missing_from_db, f"{table_name}: Core columns with no physical counterpart: {missing_from_db}"
