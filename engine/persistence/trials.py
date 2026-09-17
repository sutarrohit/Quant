"""SQLAlchemy Core mirror of the Prisma-migrated `trials` table (D-11, VALID-01, RESEARCH Pattern 4).

Hand-declared to mirror `packages/prisma/schema.prisma`'s `Trial` model column-for-column. Parity is
asserted by `engine/tests/persistence/test_schema_parity.py`, never by reflecting the live table
at import time — that would couple every import of this module to a live database and to
Prisma's exact current column set.

**The trials guarantee, precisely.** `trial_recorder` covers every exit path *after* it is
entered: normal completion, an exception raised anywhere inside the guarded block, and (from
plan 01-09) a keyboard interrupt. It cannot cover what comes before entry — a malformed CLI
invocation, an unreadable or invalid spec file, and an unreachable database each fail before a
run is identifiable, and none of them have a `params_hash` to record a row under. That is not a
lost run; there was no run. The one gap this recorder does not close is a hard kill (SIGKILL,
power loss) mid-write; the upgrade path is write-ahead-then-update (D-15's known ceiling), which
Phase 8 needs anyway for durable `clientOrderId` lineage. See `packages/prisma/README.md` for the same
boundary stated for a non-Python reader.
"""

import contextlib
import dataclasses
from collections.abc import Generator

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

metadata = sa.MetaData()

trials = sa.Table(
    "trials",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
    sa.Column("strategy_lineage_id", sa.Text, nullable=False),
    sa.Column("params_hash", sa.Text, nullable=False),
    sa.Column("objective", sa.Text, nullable=False),
    sa.Column("ran_at", sa.DateTime, nullable=False),
    sa.Column("was_oos", sa.Boolean, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("error_message", sa.Text, nullable=True),
)

NO_TRADES_OBJECTIVE = "no-trades"
"""Written when a run produced zero trades, so a zero-trade run is distinguishable from a run
whose objective genuinely evaluated to zero. Phase 3 owns the real objective definition."""


def _insert_own_transaction(conn: sa.Connection, stmt) -> None:
    """Execute one INSERT in a transaction scoped to just this statement, independent of
    whatever else the given connection is doing. The crash guarantee (D-15) requires this write
    to land even when the caller's own surrounding work is about to be abandoned."""
    owns_transaction = not conn.in_transaction()
    trans = conn.begin() if owns_transaction else conn.begin_nested()
    conn.execute(stmt)
    trans.commit()


def record_trial(
    conn: sa.Connection,
    *,
    strategy_lineage_id: str,
    params_hash: str,
    objective: str,
    was_oos: bool,
    status: str,
    error_message: str | None = None,
) -> None:
    """Insert one `trials` row via a parameterized `insert()`. Omits `id` and `ran_at` so the
    database-side defaults (migrated in plan 01-02 Task 2) fill them. Never deduplicates — two
    calls with the identical `params_hash` write two rows, by design (D-15)."""
    stmt = sa.insert(trials).values(
        strategy_lineage_id=strategy_lineage_id,
        params_hash=params_hash,
        objective=objective,
        was_oos=was_oos,
        status=status,
        error_message=error_message,
    )
    _insert_own_transaction(conn, stmt)


@dataclasses.dataclass
class _TrialHandle:
    """Yielded by `trial_recorder`. `objective` is only knowable once a run has produced
    trades, so it is set inside the guarded block via `set_objective` rather than passed at
    entry. An unset objective resolves to `NO_TRADES_OBJECTIVE` rather than null."""

    _objective: str | None = dataclasses.field(default=None, init=False)

    def set_objective(self, value: str) -> None:
        self._objective = value

    @property
    def objective(self) -> str:
        return self._objective if self._objective is not None else NO_TRADES_OBJECTIVE


# ponytail: a hard kill (SIGKILL, power loss) between entry and the final INSERT still loses the
# row — the known D-15 ceiling. Upgrade path: write-ahead-then-update, which Phase 8 needs
# anyway for durable clientOrderId lineage.
@contextlib.contextmanager
def trial_recorder(
    conn: sa.Connection, *, strategy_lineage_id: str, params_hash: str, was_oos: bool
) -> Generator[_TrialHandle]:
    """Context manager wrapping one backtest run. Writes exactly one `trials` row on every exit
    path from this point onward: `status="completed"` on normal exit, `status="crashed"` with the
    exception's string form on any exception (re-raised after recording). See the module
    docstring for the exact guaranteed window."""
    handle = _TrialHandle()
    try:
        yield handle
    except Exception as exc:
        record_trial(
            conn,
            strategy_lineage_id=strategy_lineage_id,
            params_hash=params_hash,
            objective=handle.objective,
            was_oos=was_oos,
            status="crashed",
            error_message=str(exc),
        )
        raise
    else:
        record_trial(
            conn,
            strategy_lineage_id=strategy_lineage_id,
            params_hash=params_hash,
            objective=handle.objective,
            was_oos=was_oos,
            status="completed",
            error_message=None,
        )
