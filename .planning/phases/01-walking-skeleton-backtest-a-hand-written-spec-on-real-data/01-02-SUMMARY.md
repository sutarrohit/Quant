---
phase: 01-walking-skeleton-backtest-a-hand-written-spec-on-real-data
plan: 02
subsystem: persistence
tags: [prisma, postgres, sqlalchemy-core, docker-compose, migrations]

# Dependency graph
requires: ["01-01"]
provides:
  - "prisma/ standalone workspace package (@repo/prisma) as sole Prisma schema owner (D-11), carrying the four better-auth models verbatim plus Trial, SnapshotCapture, SymbolListingSnapshot"
  - "Root docker-compose.yml with a single postgres:17 service (D-10), replacing both per-app template compose files"
  - "Applied migration prisma/migrations/20260906125454_phase1_trials_and_symbol_snapshots — trials, snapshot_capture, symbol_listing_snapshot exist in the live database with snake_case physical columns and DB-generated UUID defaults"
  - "engine/persistence/db.py, trials.py, snapshots.py — the Python write path plan 01-05 (tracer) and 01-06 (cron) call: record_trial(), trial_recorder(), record_capture()"
affects: [01-05, 01-06, 01-09]

# Actuals (#2632)
actuals:
  tokens: 10988
  tasks: 3
  commits: 4

# Tech tracking
tech-stack:
  added: ["@repo/prisma workspace package", "postgres:17 (docker compose)", "psycopg (v3) SQLAlchemy dialect"]
  patterns:
    - "Prisma models carry explicit @map(\"snake_case\") on every multi-word field; hand-declared SQLAlchemy Core Table mirrors bind to the same physical columns, parity asserted by a two-way test rather than autoload/reflection"
    - "New tables use @default(dbgenerated(\"gen_random_uuid()\")) @db.Uuid, not the four existing models' client-side @default(uuid()), so a bare Core INSERT omitting id succeeds"
    - "trial_recorder/record_capture each open their own transaction on the given Connection (conn.begin() if not already in one, else begin_nested()) and commit/rollback independent of the caller's surrounding work — the write is the atomic unit, not the caller's session"
    - "DATABASE_URL is shared verbatim between Prisma (TS) and SQLAlchemy (Python); engine_from_env() rewrites the postgresql:// scheme to postgresql+psycopg:// since the pinned Python driver is psycopg v3, not psycopg2"

key-files:
  created:
    - prisma/schema.prisma
    - prisma/prisma.config.ts
    - prisma/package.json
    - prisma/.env.example
    - prisma/README.md
    - prisma/migrations/20260906125454_phase1_trials_and_symbol_snapshots/migration.sql
    - docker-compose.yml
    - engine/persistence/db.py
    - engine/persistence/trials.py
    - engine/persistence/snapshots.py
    - engine/tests/persistence/__init__.py
    - engine/tests/persistence/conftest.py
    - engine/tests/persistence/test_trials.py
    - engine/tests/persistence/test_schema_parity.py
  modified:
    - .gitignore
    - pnpm-lock.yaml
  deleted:
    - apps/server/docker-compose.yml

key-decisions:
  - "Config-path probe (per plan instruction, not assumed): prisma/prisma.config.ts resolves schema/migrations paths relative to its own location, confirmed against Prisma's own docs (paths in prisma.config.ts resolve relative to the config file, not the invoking cwd) and empirically via `prisma validate` — config-relative form (`schema.prisma`, `migrations`) validated on the first try, no fallback needed"
  - "engine_from_env() normalizes postgresql:// to postgresql+psycopg:// — SQLAlchemy defaults to the psycopg2 dialect for a bare postgresql:// URL, but engine/pyproject.toml pins psycopg (v3) binary, not psycopg2; rewriting the scheme keeps one DATABASE_URL value shared across Prisma and Python instead of requiring two"
  - "Added __pycache__/ and *.pyc to root .gitignore — Python bytecode caches were accumulating as untracked debris since plan 01-01 (unlike .venv/.pytest_cache/.ruff_cache, which each ship their own internal .gitignore)"

requirements-completed: [VALID-01, DATA-03]

coverage:
  - id: D1
    description: "prisma/schema.prisma declares Trial, SnapshotCapture, SymbolListingSnapshot with DB-generated UUID defaults and explicit snake_case @map on every multi-word field"
    requirement: "VALID-01, DATA-03"
    verification:
      - kind: other
        ref: "grep -c 'gen_random_uuid()' prisma/schema.prisma -> 3"
        status: pass
      - kind: other
        ref: "grep -cE '@map(\"[a-z0-9]+(_[a-z0-9]+)+\")' prisma/schema.prisma -> 20 (>=14 required)"
        status: pass
      - kind: other
        ref: "pnpm --filter @repo/prisma exec prisma validate"
        status: pass
    human_judgment: false
  - id: D2
    description: "Single root Postgres compose; migration applied; physical columns snake_case on the live database"
    requirement: "VALID-01, DATA-03"
    verification:
      - kind: other
        ref: "docker compose up -d postgres && docker compose exec -T postgres pg_isready -U quant -> accepting connections"
        status: pass
      - kind: other
        ref: "SELECT count(*) FROM information_schema.columns WHERE table_name IN ('trials','snapshot_capture','symbol_listing_snapshot') AND column_name ~ '[A-Z]' -> 0"
        status: pass
      - kind: other
        ref: "ls -1 docker-compose.yml apps/server/docker-compose.yml packages/fastapi-server/docker-compose.yml | wc -l -> 1"
        status: pass
    human_judgment: false
  - id: D3
    description: "SQLAlchemy Core writers: record_trial, trial_recorder, record_capture, two-way schema parity"
    requirement: "VALID-01"
    verification:
      - kind: unit
        ref: "uv run --project engine pytest engine/tests/persistence -q -> 13 passed"
        status: pass
      - kind: other
        ref: "grep -c 'autoload_with' engine/persistence/trials.py engine/persistence/snapshots.py -> 0, 0"
        status: pass
      - kind: other
        ref: "uv run --project engine ruff check engine/persistence -> clean"
        status: pass
    human_judgment: false

# Metrics
duration: 14min
completed: 2026-09-06
status: complete
---

# Phase 1 Plan 2: Persistence — Prisma Schema, Postgres, and SQLAlchemy Core Writers Summary

**Prisma extracted into `@repo/prisma`, owning `trials` and the two `snapshot_capture`/`symbol_listing_snapshot` tables with DB-generated UUIDs and explicit snake_case columns; a single root Postgres compose replaces the two template files and the migration is applied; `engine/persistence/` gives Python a tested, atomic write path into all three tables.**

## Performance

- **Duration:** ~14 min
- **Tasks:** 3
- **Commits:** 4
- **Files changed:** 18 (excluding pnpm-lock.yaml churn)

## Accomplishments

- `prisma/` stands up as a standalone workspace package, carrying the four better-auth models verbatim (untouched, no `@map`) plus three new models: `Trial` (→ `trials`), `SnapshotCapture` (→ `snapshot_capture`), `SymbolListingSnapshot` (→ `symbol_listing_snapshot`), all with `@id @default(dbgenerated("gen_random_uuid()")) @db.Uuid` and 20 explicit `@map` directives across their multi-word fields.
- The config-path ambiguity flagged by cross-AI review was resolved by probe rather than assumption: `prisma.config.ts` sitting inside `prisma/` resolves `schema`/`migrations` paths relative to itself, confirmed both against Prisma's own docs and by a passing `prisma validate` on the first attempt.
- A single root `docker-compose.yml` (postgres:17, healthcheck, named volume) replaces `apps/server/docker-compose.yml` (deleted this plan) and `packages/fastapi-server/docker-compose.yml` (already gone as of plan 01-01) — exactly one compose file now exists.
- Migration `20260906125454_phase1_trials_and_symbol_snapshots` applied and committed; verified against the live database (not just the schema file) that no physical column on the three new tables has a capitalised character, and `strategy_lineage_id` exists as a real column.
- `engine/persistence/trials.py` and `snapshots.py` mirror the Prisma tables as hand-declared SQLAlchemy Core `Table` objects (no reflection/autoload), exposing `record_trial`, `trial_recorder` (crash-safe, `set_objective` handle, `NO_TRADES_OBJECTIVE` marker), and `record_capture` (atomic parent+children write, no child-only writer). 13/13 TDD tests pass, including the crash path, capture atomicity, shared-instant, retry-visibility, and two-way schema-parity behaviors.
- The exact trials guarantee window (every exit path after `trial_recorder` entry; nothing before) is written down in both `trials.py`'s module docstring and `prisma/README.md`, per the plan's requirement that a reviewer or future implementer see the boundary in both places.

## Task Commits

1. **Task 1: Extract the Prisma package and declare the two Phase 1 tables** — `70c0059` (feat)
2. **Task 2: Root Postgres compose and the schema migration [BLOCKING]** — `d0db81d` (feat)
3. **Task 3: SQLAlchemy Core writers for trials and snapshots (TDD)**
   - `6118d14` (test) — RED: 13 tests, fails on `ModuleNotFoundError: No module named 'persistence.db'`
   - `2b2fc63` (feat) — GREEN: `db.py`/`trials.py`/`snapshots.py` implemented, 13/13 passing, ruff clean

**Plan metadata:** (this commit, following SUMMARY)

## Files Created/Modified

- `prisma/schema.prisma` — datasource/generator + four better-auth models (verbatim) + `Trial`, `SnapshotCapture`, `SymbolListingSnapshot`
- `prisma/prisma.config.ts` — `engine: "classic"`, config-relative `schema`/`migrations` paths, direct `process.env.DATABASE_URL` read (no `./src/env.js`, no `DIRECT_URL`)
- `prisma/package.json` — `@repo/prisma`, scripts `db:migrate`/`db:deploy`/`db:generate`/`build`
- `prisma/.env.example` — single `DATABASE_URL=postgresql://quant:quant@localhost:5432/quant`
- `prisma/README.md` — config-path probe result, ID-default deviation, two-divergent-schema reconciliation note, no-dedup rationale, trials guarantee window
- `prisma/migrations/20260906125454_phase1_trials_and_symbol_snapshots/migration.sql` — committed, applied
- `docker-compose.yml` — root, single `postgres:17` service
- `engine/persistence/db.py` — `engine_from_env()` (scheme rewrite for psycopg v3), `session_scope()`
- `engine/persistence/trials.py` — `trials` Table, `record_trial()`, `trial_recorder()`, `NO_TRADES_OBJECTIVE`
- `engine/persistence/snapshots.py` — `snapshot_capture`/`symbol_listing_snapshot` Tables, `record_capture()`
- `engine/tests/persistence/{__init__.py,conftest.py,test_trials.py,test_schema_parity.py}` — 13 tests, fixtures default `DATABASE_URL` to the local compose value
- `.gitignore` — added `__pycache__/`, `*.pyc`
- Deleted: `apps/server/docker-compose.yml`

## Decisions Made

- Config-relative path form (`schema.prisma`, `migrations`) confirmed correct via Context7-sourced Prisma docs ("paths ... resolved relative to the config file's location") and empirically via `prisma validate` — no fallback to the `prisma/`-prefixed form was needed.
- `engine_from_env()` rewrites `postgresql://` → `postgresql+psycopg://` so the single `DATABASE_URL` value in `prisma/.env.example` works unchanged for both Prisma (TS) and SQLAlchemy (Python), rather than maintaining two URL formats.
- `record_trial`/`record_capture` each manage their own transaction on the given `Connection` (fresh `begin()` or a `begin_nested()` savepoint if one is already active) so the write commits independently of whatever else that connection was doing — required for the D-15 crash guarantee to actually hold when `trial_recorder` is entered mid-run.
- Added `server_default=sa.text("gen_random_uuid()")` on the three new tables' Core `id` columns (informational to SQLAlchemy only, no DDL emitted) to silence a `SAWarning` about primary keys with no indicated default — the physical DEFAULT already exists in Postgres per Task 2's migration; this just tells the Core layer about it.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] SQLAlchemy defaulted to the psycopg2 dialect for a bare `postgresql://` URL**
- **Found during:** Task 3, first GREEN test run
- **Issue:** `engine/pyproject.toml` (plan 01-01) pins `psycopg[binary]` (v3), not `psycopg2`. `sqlalchemy.create_engine("postgresql://...")` resolves to the `psycopg2` dialect by default and raised `ModuleNotFoundError: No module named 'psycopg2'` on every test.
- **Fix:** `engine_from_env()` rewrites a `postgresql://` prefix to `postgresql+psycopg://` before calling `create_engine`, so the one `DATABASE_URL` value in `prisma/.env.example` (shared with Prisma) works for both toolchains without needing two different connection-string formats.
- **Files modified:** `engine/persistence/db.py`
- **Verification:** `uv run --project engine pytest engine/tests/persistence -q` — 13/13 passing.
- **Committed in:** `2b2fc63` (Task 3 GREEN commit)

**2. [Rule 1 - Bug] Docstrings referencing `autoload_with` broke the plan's own literal-string verify gate**
- **Found during:** Task 3, verify pass
- **Issue:** `trials.py` and `snapshots.py` docstrings explained the deliberate choice not to use `autoload_with` by naming it — which made `grep -c 'autoload_with' ...` print `1` instead of the required `0`, since the check has no way to distinguish "uses it" from "mentions it while explaining why it's avoided."
- **Fix:** Reworded both docstrings to describe the avoided behavior ("reflecting the live table at import time") without the literal identifier.
- **Files modified:** `engine/persistence/trials.py`, `engine/persistence/snapshots.py`
- **Verification:** `grep -c 'autoload_with' engine/persistence/trials.py engine/persistence/snapshots.py` → `0`, `0`.
- **Committed in:** `2b2fc63` (Task 3 GREEN commit)

**3. [Rule 3 - Blocking] `__pycache__/` directories accumulating as untracked debris**
- **Found during:** Task 3, post-commit untracked-file check
- **Issue:** Unlike `.venv/`, `.pytest_cache/`, and `.ruff_cache/` (each of which ships its own internal `.gitignore` with `*`), Python's `__pycache__/` directories carry no such file and were showing as untracked (`??`) after every test run since plan 01-01.
- **Fix:** Added `__pycache__/` and `*.pyc` to the root `.gitignore`.
- **Files modified:** `.gitignore`
- **Verification:** `git status --short --ignored engine/` shows all four cache directory kinds as `!!` (ignored).
- **Committed in:** `2b2fc63` (Task 3 GREEN commit)

**4. [Rule 2 - Missing critical functionality] `prisma/README.md` scope extended beyond Task 3's `<files>` list**
- **Found during:** Task 1 (anticipating Task 3's action text)
- **Issue:** Task 3's `<action>` explicitly requires stating the trials guarantee window "in `prisma/README.md` in exactly those terms," but the plan's Task 3 `<files>` list only names `engine/*` paths — `prisma/README.md` is not listed there.
- **Fix:** Wrote the guarantee-window section into `prisma/README.md` during Task 1 (when the file was first created), since the content applies regardless of which task's commit it lands in, and the plan's action text for Task 3 is unambiguous about the requirement.
- **Files modified:** `prisma/README.md` (committed in Task 1, `70c0059`, not Task 3)
- **Verification:** `prisma/README.md` contains the "## The trials guarantee: exact window" section.
- **Committed in:** `70c0059` (Task 1 commit)

---

**Total deviations:** 4 auto-fixed (1 blocking driver mismatch, 1 bug in a self-referential verify gate, 1 blocking gitignore gap, 1 documentation-scope correction). None architectural; no Rule 4 checkpoints raised.

## Issues Encountered

- `pnpm turbo run build --filter=@repo/prisma` (i.e. `prisma generate`) fails locally without `DATABASE_URL` present in the task's environment, because `prisma.config.ts` reads and validates the env var eagerly at config-load time — even though generating the client's TypeScript types does not require a live database connection. This matches the pre-existing behavior of `apps/server/prisma.config.ts` (which throws on a missing `DIRECT_URL` the same way) and is not a regression this plan introduced. It is out of scope for this plan's verification: D-08's CI pipeline is `turbo run test lint check-types`, not `build`, and `@repo/prisma` does not currently define `test`/`lint`/`check-types` scripts, so nothing in the required pipeline depends on this today. Flagging for whichever later plan (Phase 4, when `apps/server` links against the generated client) first needs `turbo run build` to succeed in CI: `DATABASE_URL` must be present in that job's environment.
- A shell-level `DATABASE_URL=... pnpm turbo run build ...` did not reach the child task process in local testing — likely Turborepo's env-passthrough filtering. Worked around by verifying `prisma generate`/`prisma validate` directly via `pnpm --filter @repo/prisma exec prisma ...` instead, which is also how the plan's own `<verify>` commands invoke it.

## User Setup Required

- Docker daemon must be running and port 5432 free before `docker compose up -d postgres` — verified present and functioning on this machine (Docker Compose v5.1.2, port free) before Task 2 ran; no separate approval gate needed since this plan's `user_setup` only names the same precondition already satisfied.
- `prisma/.env` (gitignored) must be created locally from `prisma/.env.example` before running any `pnpm --filter @repo/prisma` command that needs to reach the database — not created as a committed file; verification in this session used an inline `DATABASE_URL=...` env var instead of writing the file.

## Next Phase Readiness

- `engine/persistence/{db,trials,snapshots}.py` are ready for plan 01-05 (the tracer, wraps the first real backtest in `trial_recorder`) and plan 01-06 (the daily cron, calls `record_capture`) to import directly via `from persistence.trials import trial_recorder` / `from persistence.snapshots import record_capture` (note: `engine/` has no top-level `__init__.py`, so imports are `persistence.*`, not `engine.persistence.*` — confirmed empirically, matches the existing `engine/tests/dsl` convention).
- `prisma/README.md`'s two-divergent-schema note is a live tracking item for Phase 4 — nothing to do now, but the merge burden is documented with both file paths named.
- No blockers. The one open item (`turbo run build` needing `DATABASE_URL` in CI) is deferred to whichever plan first wires `apps/server` against the generated Prisma client.

## Self-Check: PASSED

All created files verified present on disk: `prisma/schema.prisma`, `prisma/prisma.config.ts`,
`prisma/package.json`, `prisma/.env.example`, `prisma/README.md`,
`prisma/migrations/20260906125454_phase1_trials_and_symbol_snapshots/migration.sql`,
`docker-compose.yml`, `engine/persistence/db.py`, `engine/persistence/trials.py`,
`engine/persistence/snapshots.py`, `engine/tests/persistence/{__init__.py,conftest.py,test_trials.py,test_schema_parity.py}`.
All cited commit hashes (`70c0059`, `d0db81d`, `6118d14`, `2b2fc63`) verified present in `git log`.
`apps/server/docker-compose.yml` verified absent (deleted). Live database verified via
`docker compose exec -T postgres psql` to hold `trials`, `snapshot_capture`,
`symbol_listing_snapshot` with 0 rows each and no capitalised physical column names.

## Self-Check: PASSED (verified)

Re-verified independently after writing this summary: all 14 created/modified files present on
disk, `apps/server/docker-compose.yml` confirmed absent, and all 4 commit hashes present in
`git log --oneline --all`.

---
*Phase: 01-walking-skeleton-backtest-a-hand-written-spec-on-real-data*
*Completed: 2026-09-06*
