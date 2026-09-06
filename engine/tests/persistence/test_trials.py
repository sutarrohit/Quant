"""Behavior tests for engine/persistence/trials.py and engine/persistence/snapshots.py
(VALID-01, DATA-03, D-15) — run against the live compose Postgres (D-10)."""

import datetime
import decimal
import hashlib

import pytest
import sqlalchemy as sa

from persistence.snapshots import record_capture, snapshot_capture, symbol_listing_snapshot
from persistence.trials import NO_TRADES_OBJECTIVE, record_trial, trial_recorder, trials


def _count(conn, table) -> int:
    return conn.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()


def test_record_trial_inserts_one_row(conn):
    before = _count(conn, trials)
    record_trial(
        conn,
        strategy_lineage_id="lineage-1",
        params_hash="hash-1",
        objective="1.5",
        was_oos=False,
        status="completed",
    )
    assert _count(conn, trials) == before + 1


def test_trial_recorder_records_crash(conn):
    with (
        pytest.raises(RuntimeError),
        trial_recorder(conn, strategy_lineage_id="lineage-crash", params_hash="hash-crash", was_oos=False),
    ):
        raise RuntimeError("boom")

    row = conn.execute(
        sa.select(trials.c.status, trials.c.error_message).where(trials.c.params_hash == "hash-crash")
    ).one()
    assert row.status == "crashed"
    assert row.error_message is not None
    assert "boom" in row.error_message


def test_record_trial_does_not_dedup(conn):
    for _ in range(2):
        record_trial(
            conn,
            strategy_lineage_id="lineage-dup",
            params_hash="hash-dup",
            objective="0.1",
            was_oos=True,
            status="completed",
        )
    count = conn.execute(
        sa.select(sa.func.count()).select_from(trials).where(trials.c.params_hash == "hash-dup")
    ).scalar_one()
    assert count == 2


def test_record_trial_omits_id_and_ran_at(conn):
    record_trial(
        conn,
        strategy_lineage_id="lineage-defaults",
        params_hash="hash-defaults",
        objective="0.2",
        was_oos=False,
        status="completed",
    )
    row = conn.execute(sa.select(trials.c.id, trials.c.ran_at).where(trials.c.params_hash == "hash-defaults")).one()
    assert row.id is not None
    assert row.ran_at is not None


def test_zero_trades_writes_no_trades_marker(conn):
    with trial_recorder(conn, strategy_lineage_id="lineage-zero", params_hash="hash-zero", was_oos=False):
        pass  # produced no trades; never calls set_objective

    row = conn.execute(sa.select(trials.c.objective).where(trials.c.params_hash == "hash-zero")).one()
    assert row.objective == NO_TRADES_OBJECTIVE


def test_ordering_is_stable_for_shared_ran_at(conn):
    shared_ts = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    for i in range(3):
        conn.execute(
            sa.insert(trials).values(
                strategy_lineage_id="lineage-order",
                params_hash=f"hash-order-{i}",
                objective="0.0",
                ran_at=shared_ts,
                was_oos=False,
                status="completed",
            )
        )
    conn.commit()

    def _ordered_ids():
        return [
            row.id
            for row in conn.execute(
                sa.select(trials.c.id)
                .where(trials.c.strategy_lineage_id == "lineage-order")
                .order_by(trials.c.ran_at, trials.c.id)
            )
        ]

    first = _ordered_ids()
    second = _ordered_ids()
    assert first == second
    assert first == sorted(first, key=str)


def test_objective_set_late_inside_guarded_block(conn):
    with trial_recorder(conn, strategy_lineage_id="lineage-late", params_hash="hash-late", was_oos=False) as handle:
        handle.set_objective("2.75")

    row = conn.execute(sa.select(trials.c.objective).where(trials.c.params_hash == "hash-late")).one()
    assert row.objective == "2.75"


def _sample_symbol_row(symbol: str = "BTCUSDT") -> dict:
    return {
        "raw_payload": b"gzip-compressed-exchange-info-bytes",
        "symbol": symbol,
        "status": "TRADING",
        "base_asset": "BTC",
        "quote_asset": "USDT",
        "tick_size": decimal.Decimal("0.01"),
        "step_size": decimal.Decimal("0.00001"),
        "min_notional": decimal.Decimal("10.00"),
    }


def test_record_capture_atomic_child_failure_leaves_nothing(conn):
    captured_at = datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC)
    good_row = _sample_symbol_row("ETHUSDT")
    bad_row = _sample_symbol_row("BADUSDT")
    bad_row["base_asset"] = None  # violates the NOT NULL constraint, after the parent already exists

    with pytest.raises(sa.exc.IntegrityError):
        record_capture(
            conn,
            capture_date=datetime.date(2026, 1, 2),
            captured_at=captured_at,
            payload_sha256=hashlib.sha256(b"payload-2").hexdigest(),
            expected_symbol_count=2,
            rows=[good_row, bad_row],
        )

    assert _count(conn, snapshot_capture) == 0
    assert _count(conn, symbol_listing_snapshot) == 0


def test_record_capture_shares_one_captured_at(conn):
    captured_at = datetime.datetime(2026, 1, 3, 12, 0, 0, tzinfo=datetime.UTC)
    rows = [_sample_symbol_row("AAAUSDT"), _sample_symbol_row("BBBUSDT")]
    record_capture(
        conn,
        capture_date=datetime.date(2026, 1, 3),
        captured_at=captured_at,
        payload_sha256=hashlib.sha256(b"payload-3").hexdigest(),
        expected_symbol_count=2,
        rows=rows,
    )

    parent = conn.execute(
        sa.select(
            snapshot_capture.c.id,
            snapshot_capture.c.captured_at,
            snapshot_capture.c.status,
            snapshot_capture.c.actual_symbol_count,
        ).where(snapshot_capture.c.capture_date == datetime.date(2026, 1, 3))
    ).one()
    assert parent.status == "complete"
    assert parent.actual_symbol_count == 2

    child_timestamps = (
        conn.execute(
            sa.select(symbol_listing_snapshot.c.captured_at).where(symbol_listing_snapshot.c.capture_id == parent.id)
        )
        .scalars()
        .all()
    )
    assert len(child_timestamps) == 2
    assert all(ts == parent.captured_at for ts in child_timestamps)


def test_record_capture_retry_is_visible_not_deduped(conn):
    capture_date = datetime.date(2026, 1, 4)
    captured_at = datetime.datetime(2026, 1, 4, tzinfo=datetime.UTC)
    for _ in range(2):
        record_capture(
            conn,
            capture_date=capture_date,
            captured_at=captured_at,
            payload_sha256=hashlib.sha256(b"payload-4").hexdigest(),
            expected_symbol_count=1,
            rows=[_sample_symbol_row("CCCUSDT")],
        )

    statuses = (
        conn.execute(sa.select(snapshot_capture.c.status).where(snapshot_capture.c.capture_date == capture_date))
        .scalars()
        .all()
    )
    assert len(statuses) == 2
    assert all(status == "complete" for status in statuses)
