"""SQLAlchemy Core mirrors of the Prisma-migrated `snapshot_capture` and
`symbol_listing_snapshot` tables (D-11, DATA-03, RESEARCH Pattern 4).

Hand-declared to mirror `prisma/schema.prisma`'s `SnapshotCapture` and `SymbolListingSnapshot`
models column-for-column; parity is asserted by
`engine/tests/persistence/test_schema_parity.py`, never by reflecting the live table at import
time. There is deliberately no child-only writer: a caller able to insert `symbol_listing_snapshot` rows without a
`snapshot_capture` parent is a caller able to recreate the exact partial-capture ambiguity the
parent exists to remove (D-14).
"""

import decimal
from collections.abc import Iterable, Mapping
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

metadata = sa.MetaData()

snapshot_capture = sa.Table(
    "snapshot_capture",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
    sa.Column("capture_date", sa.Date, nullable=False),
    sa.Column("captured_at", sa.DateTime, nullable=False),
    sa.Column("payload_sha256", sa.Text, nullable=False),
    sa.Column("expected_symbol_count", sa.Integer, nullable=False),
    sa.Column("actual_symbol_count", sa.Integer, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
)

symbol_listing_snapshot = sa.Table(
    "symbol_listing_snapshot",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
    sa.Column(
        "capture_id",
        UUID(as_uuid=True),
        sa.ForeignKey("snapshot_capture.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("raw_payload", sa.LargeBinary, nullable=False),
    sa.Column("symbol", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("base_asset", sa.Text, nullable=False),
    sa.Column("quote_asset", sa.Text, nullable=False),
    sa.Column("tick_size", sa.Numeric(38, 18), nullable=False),
    sa.Column("step_size", sa.Numeric(38, 18), nullable=False),
    sa.Column("min_notional", sa.Numeric(38, 18), nullable=True),
    sa.Column("captured_at", sa.DateTime, nullable=False),
)

_DECIMAL_FIELDS = ("tick_size", "step_size", "min_notional")


def _assert_decimal_money(rows: Iterable[Mapping]) -> None:
    """Money-shaped columns bind `decimal.Decimal`, never `float` — a float smuggled in here
    would silently round-trip through Postgres NUMERIC with no exception anywhere upstream."""
    for row in rows:
        for field in _DECIMAL_FIELDS:
            value = row.get(field)
            if value is not None and not isinstance(value, decimal.Decimal):
                raise TypeError(f"{field} must be a decimal.Decimal, got {type(value)!r}")


def record_capture(
    conn: sa.Connection,
    *,
    capture_date: date,
    captured_at: datetime,
    payload_sha256: str,
    expected_symbol_count: int,
    rows: Iterable[Mapping],
) -> None:
    """Write one daily capture: a `snapshot_capture` parent plus its `symbol_listing_snapshot`
    children, atomically. Either the whole capture lands or none of it does — there is no
    partial-capture state visible after this returns. `captured_at` is the single instant shared
    by the parent and every child row, passed in by the caller rather than defaulted per
    statement, so a batch of several hundred inserts cannot straddle a clock read across a
    calendar-date boundary."""
    rows = list(rows)
    _assert_decimal_money(rows)

    owns_transaction = not conn.in_transaction()
    trans = conn.begin() if owns_transaction else conn.begin_nested()
    try:
        parent_id = conn.execute(
            sa.insert(snapshot_capture)
            .values(
                capture_date=capture_date,
                captured_at=captured_at,
                payload_sha256=payload_sha256,
                expected_symbol_count=expected_symbol_count,
                actual_symbol_count=0,
                status="started",
            )
            .returning(snapshot_capture.c.id)
        ).scalar_one()

        written = 0
        for row in rows:
            conn.execute(
                sa.insert(symbol_listing_snapshot).values(
                    capture_id=parent_id,
                    captured_at=captured_at,
                    **row,
                )
            )
            written += 1

        conn.execute(
            sa.update(snapshot_capture)
            .where(snapshot_capture.c.id == parent_id)
            .values(status="complete", actual_symbol_count=written)
        )
    except Exception:
        trans.rollback()
        raise
    else:
        trans.commit()
