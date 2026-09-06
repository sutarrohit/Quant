---
phase: 01-walking-skeleton-backtest-a-hand-written-spec-on-real-data
plan: 01
subsystem: infra
tags: [turborepo, pnpm-workspace, uv, pytest, ruff, fastapi]

# Dependency graph
requires: []
provides:
  - "engine/ as a resolvable uv project (Python 3.13) with dsl/, adapters/, data/, cli/, persistence/, tests/ subpackages"
  - "engine/tests/conftest.py synthetic_bars fixture (48 deterministic bars, decimal-string OHLCV, nanosecond ts_event) for engine-free DSL unit tests"
  - "pnpm-workspace.yaml scoped to packages/*, engine, prisma, schemas — apps/web and apps/server de-listed but still tracked in git"
  - "packages/fastapi-server stripped of the fastapi-blog domain, reserved as the Phase 5 supervisor surface with a bare /health endpoint"
  - "gitignore rules for generated contract artifacts, run outputs, and the local data-cache"
affects: [01-02, 01-03, 01-04, 01-05, 01-06, 01-07, 01-08, 01-09]

# Actuals (#2632)
actuals:
  tokens: 23073
  tasks: 3
  commits: 4

# Tech tracking
tech-stack:
  added: [uv, ruff, pytest, pydantic, sqlalchemy, "psycopg[binary]", pyarrow, matplotlib, datamodel-code-generator]
  patterns:
    - "engine/package.json as a turbo shim delegating build/lint/format/check-types/test to uv"
    - "frozen dataclass + decimal-string fields for OHLCV test fixtures (never touches float)"

key-files:
  created:
    - engine/pyproject.toml
    - engine/package.json
    - engine/README.md
    - engine/tests/conftest.py
    - engine/tests/dsl/test_scaffold_smoke.py
    - engine/dsl/__init__.py
    - engine/adapters/__init__.py
    - engine/data/__init__.py
    - engine/cli/__init__.py
    - engine/persistence/__init__.py
  modified:
    - package.json
    - pnpm-workspace.yaml
    - .gitignore
    - packages/fastapi-server/pyproject.toml
    - packages/fastapi-server/package.json
    - packages/fastapi-server/main.py
    - packages/fastapi-server/README.md

key-decisions:
  - "Package-legitimacy gate (Task 1) approved by human for all twelve [SUS]-flagged packages after review — verdicts were a checker false-positive (too-new = latest release date, not founding date)"
  - "Fully stripped packages/fastapi-server's blog domain (routers, models, auth, alembic, docker-compose, service/schema/scripts/tests) rather than leaving broken imports after removing sqlalchemy/aiosqlite/pwdlib/pyjwt/pydantic-settings/alembic — reduced to a bare FastAPI app with /health, matching D-03's 'reserved, no Phase 1 role' framing"
  - "Regenerated packages/fastapi-server/uv.lock after trimming its dependencies, since its turbo build script (uv sync --frozen) would otherwise fail against a stale lock"
  - "synthetic_bars fixture uses a 16-bar-period sine wave over 48 bars (verified via script: SMA5/SMA20 cross down@27, up@35, down@43) rather than a hand-tuned zig-zag, for a reproducible, easily-extended shape"

patterns-established:
  - "Pattern 1: engine/*/__init__.py subpackages stay empty scaffolding until a later plan needs them"
  - "Pattern 2: purity-gate directories (engine/dsl/) document their own constraint in README.md, never in an in-directory comment, so the literal grep stays self-consistent"

requirements-completed: [FOUND-05, FOUND-06]

coverage:
  - id: D1
    description: "engine/ exists as a resolvable uv project with dsl/, adapters/, data/, cli/, persistence/, tests/ and a passing pytest suite"
    requirement: "FOUND-05"
    verification:
      - kind: unit
        ref: "uv run --project engine pytest engine/tests/dsl -q"
        status: pass
      - kind: other
        ref: "test -f engine/uv.lock && test -d engine/dsl && test -d engine/adapters"
        status: pass
    human_judgment: false
  - id: D2
    description: "engine/dsl/ stays free of any nautilus_trader import (purity gate for the pure-Python DSL seam)"
    requirement: "FOUND-06"
    verification:
      - kind: other
        ref: "grep -rl nautilus_trader engine/dsl/ (exit 1, no match)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Workspace restructured to packages/*, engine, prisma, schemas — apps/* de-listed but not deleted from git"
    verification:
      - kind: other
        ref: "pnpm install (real, non-lockfile-only) and pnpm install --lockfile-only both exit 0; git ls-files apps/web apps/server returns 101 files"
        status: pass
    human_judgment: false
  - id: D4
    description: "packages/fastapi-server stripped of the fastapi-blog domain and reserved for Phase 5"
    verification:
      - kind: unit
        ref: "packages/fastapi-server/tests/test_health.py#test_health"
        status: pass
      - kind: other
        ref: "grep -cE 'aiosqlite|alembic|pwdlib|pyjwt' packages/fastapi-server/pyproject.toml -> 0"
        status: pass
    human_judgment: false
  - id: D5
    description: "Package-legitimacy gate cleared for all twelve [SUS]-flagged packages before first install"
    verification: []
    human_judgment: true
    rationale: "Human review of each PyPI/npm page against RESEARCH.md's Package Legitimacy Audit is not automatable — the checkpoint exists specifically because a human, not a script, must look before code executes at install time."

# Metrics
duration: 8min
completed: 2026-09-06
status: complete
---

# Phase 1 Plan 1: Workspace Restructure and Engine Scaffold Summary

**Turborepo restructured to `packages/*, engine, prisma, schemas`; `engine/` stood up as a Python 3.13 uv project with ruff + pytest and a green synthetic-bar test suite; `packages/fastapi-server` stripped of its fastapi-blog domain down to a bare `/health` app reserved for Phase 5.**

## Performance

- **Duration:** 8 min (12:39:39Z – 12:47:22Z)
- **Started:** 2026-09-06T12:39:39Z
- **Completed:** 2026-09-06T12:47:22Z
- **Tasks:** 3
- **Files modified:** 47 (excluding lockfiles regenerated as a side effect)

## Accomplishments
- `engine/` exists as a uv project on Python 3.13 with `dsl/`, `adapters/`, `data/`, `cli/`, `persistence/`, `tests/` and a passing pytest suite (`engine/tests/dsl/test_scaffold_smoke.py`, 3/3 green via TDD RED→GREEN)
- `engine/tests/conftest.py`'s `synthetic_bars` fixture provides 48 deterministic bars (decimal-string OHLCV, nanosecond `ts_event`, strictly increasing, one hour apart) whose close series crosses a 5-period and 20-period SMA in both directions — a reusable baseline for every evaluator unit test in this phase, independent of any ingested data or Nautilus
- `grep -rl nautilus_trader engine/dsl/` already returns nothing on day one — the FOUND-06 purity gate holds before any Nautilus import exists anywhere in the repo
- Workspace restructured: root `package.json` renamed to `quant-platform`; `pnpm-workspace.yaml` now lists exactly `packages/*, engine, prisma, schemas`; `apps/web` and `apps/server` remain in git (101 tracked files) but left the workspace until Phase 4
- `packages/fastapi-server` reduced to the Phase 5 supervisor placeholder: fastapi-blog's routers, auth, SQLAlchemy models, Alembic migrations, and its own docker-compose file are gone; `pyproject.toml` depends on plain `fastapi` only

## Task Commits

1. **Task 1: Package legitimacy gate** — no commit (checkpoint only; see Decisions Made)
2. **Task 2: Restructure the workspace to the target tree** - `466f480` (feat)
3. **Task 3: Create the engine/ uv project (TDD)**
   - `ad96c8d` (test) — RED: scaffold + failing `test_scaffold_smoke.py` (fixture not found)
   - `d0e70ff` (feat) — GREEN: `synthetic_bars` fixture implemented, 3/3 passing
   - `71225f0` (chore) — pnpm-lock.yaml updated for the new `engine` workspace importer

**Plan metadata:** (this commit, following SUMMARY)

## Files Created/Modified

- `engine/pyproject.toml` — uv project def, ruff (line-length 120, py313, E/F/I/UP/B/SIM/C4), pytest `testpaths=["tests"]`; deps `pydantic`, `sqlalchemy`, `psycopg[binary]`, `pyarrow`, `matplotlib`; dev group `pytest`, `ruff`, `datamodel-code-generator`
- `engine/package.json` — `@repo/engine` turbo shim (`build`/`lint`/`format`/`check-types`/`test` → `uv run ...`)
- `engine/README.md` — states the `engine/dsl/` purity rule outside the grepped path
- `engine/dsl/`, `engine/adapters/`, `engine/data/`, `engine/cli/`, `engine/persistence/`, `engine/tests/`, `engine/tests/dsl/` — package `__init__.py` scaffolding
- `engine/tests/conftest.py` — `SyntheticBar` frozen dataclass + `synthetic_bars` fixture
- `engine/tests/dsl/test_scaffold_smoke.py` — length, monotonic-timestamp, decimal-parseable assertions
- `engine/uv.lock` — generated by `uv sync --project engine`
- `package.json` — `name: quant-platform`
- `pnpm-workspace.yaml` — `packages/*, engine, prisma, schemas`
- `.gitignore` — generated-contract, run-output, local-cache rules
- `pnpm-lock.yaml` — updated for the `engine` workspace member
- `packages/fastapi-server/pyproject.toml` — renamed to `supervisor`; deps reduced to plain `fastapi` + existing dev group
- `packages/fastapi-server/package.json` — `db:*` scripts removed
- `packages/fastapi-server/uv.lock` — regenerated against the trimmed `pyproject.toml`
- `packages/fastapi-server/main.py` — reduced to a bare FastAPI app with `/health`
- `packages/fastapi-server/README.md` — one-paragraph "reserved for Phase 5" notice
- `packages/fastapi-server/tests/test_health.py` — new smoke test for the trimmed app (replaces deleted blog test suite)
- Deleted: `packages/fastapi-server/{alembic.ini,alembic/,auth.py,config.py,db/,docker-compose.yml,exceptions.py,media/,routers/,schema/,scripts/,service/,tests/{conftest,test_app,test_posts,test_service,test_users}.py,.env.example}`

## Decisions Made

- **Task 1 package-legitimacy gate: APPROVED.** The human reviewer confirmed all twelve `[SUS]`-flagged packages (`datamodel-code-generator`, `polars`, `pyarrow`, `pydantic`, `sqlalchemy`, `psycopg`, `matplotlib`, `pytest`, `ruff`, `prisma`, `@prisma/client`, `json-schema-to-typescript`) resolve to their expected long-established projects — RESEARCH.md's assessment that the `too-new` verdict was a checker artifact (using each package's latest release date, not its founding date) was correct. No package was rejected. Recorded here per the plan's `<done>` criterion for Task 1; this checkpoint is now cleared and must not be re-raised for this plan.
- Fully stripped `packages/fastapi-server`'s blog-domain code (not just the four explicitly-named categories) — see Deviations below.
- Chose a 16-bar-period sine wave (48 bars total) for `synthetic_bars` rather than a hand-authored zig-zag; verified by script that it crosses SMA5/SMA20 in both directions (down@27, up@35, down@43) before committing.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fully stripped packages/fastapi-server beyond the four explicitly-named deletions**
- **Found during:** Task 2
- **Issue:** The plan's `<action>` named four deletions (blog routers, models, auth modules, alembic directory, docker-compose file) plus dependency removal (`aiosqlite`, `alembic`, `pwdlib[argon2]`, `pydantic-settings`, `pyjwt`, `sqlalchemy`). `main.py`, `config.py`, `db/database.py`, `exceptions.py`, `service/`, `schema/`, `scripts/`, `tests/`, and `media/` all imported those removed modules/dependencies and would have been permanently broken (`ModuleNotFoundError` on every `import`) the moment the named deletions and dependency trim landed — that breakage is a direct, in-scope consequence of this task's own changes, not a pre-existing unrelated issue.
- **Fix:** Deleted the now-unusable files (`config.py`, `exceptions.py`, `db/`, `service/`, `schema/`, `scripts/`, `media/`, old `tests/*`) and replaced `main.py` with a minimal FastAPI app exposing only `/health`, matching the rewritten README's "reserved for Phase 5, no Phase 1 role" description. Added one smoke test (`tests/test_health.py`) so the package's own `test` script keeps working.
- **Files modified:** `packages/fastapi-server/main.py`, `+tests/test_health.py`, deletions listed above.
- **Verification:** `uv run pytest -q` (1 passed) and `uv run ruff check .` (clean) inside `packages/fastapi-server`.
- **Committed in:** `466f480` (Task 2 commit)

**2. [Rule 3 - Blocking] Regenerated packages/fastapi-server/uv.lock**
- **Found during:** Task 2
- **Issue:** `packages/fastapi-server/package.json`'s `build` script is `uv sync --frozen`, which fails if `uv.lock` doesn't match `pyproject.toml`. Trimming the dependency list without relocking would break every future `turbo run build` touching this package.
- **Fix:** Ran `uv lock` inside `packages/fastapi-server` after editing `pyproject.toml`.
- **Files modified:** `packages/fastapi-server/uv.lock`
- **Verification:** `uv run pytest` and `uv run ruff check .` both succeed against the relocked environment.
- **Committed in:** `466f480` (Task 2 commit)

**3. [Rule 3 - Blocking] Updated pnpm-lock.yaml for the new engine workspace member**
- **Found during:** Task 3, after the GREEN commit
- **Issue:** `pnpm install` (real, not `--lockfile-only`) added a two-line `engine: {}` importer entry to `pnpm-lock.yaml` once `engine/package.json` existed — an artifact of the workspace member list, not touched by the GREEN commit itself.
- **Fix:** Ran `pnpm install`, committed the resulting lockfile delta separately.
- **Files modified:** `pnpm-lock.yaml`
- **Verification:** `pnpm install` reports "Already up to date" on a subsequent run; `pnpm turbo run test --filter=@repo/engine` succeeds via the real turbo invocation path.
- **Committed in:** `71225f0`

---

**Total deviations:** 3 auto-fixed (1 bug/broken-import cascade, 2 blocking lockfile issues)
**Impact on plan:** All three were direct, mechanical consequences of the plan's own instructed changes (dependency removal, new workspace member). No scope creep beyond making the touched packages internally consistent.

## Issues Encountered

- Manually invoking `uv run --project engine pytest` (no path argument) from the **repository root** collects across the whole monorepo (including `packages/fastapi-server/tests/`) and errors, because `uv run --project X` does not change the working directory — only `X`'s venv is selected. This is not a defect in the delivered scaffold: the plan's actual `<verify>` command scopes the path explicitly (`engine/tests/dsl`), and the real invocation path — `cd engine && uv run pytest` (what `pnpm --filter @repo/engine test` / `turbo run test` does) — correctly picks up `engine/pyproject.toml`'s `testpaths` and passes cleanly (verified both ways). No fix needed; noted here so a future reader isn't surprised by the unscoped-from-root behavior.

## User Setup Required

None - no external service configuration required. Toolchain versions (`uv 0.12.0`, `pnpm 10.34.5`) were already present on the local machine and verified against the plan's `user_setup` requirement (`>=0.12,<0.13`).

## Next Phase Readiness

- `engine/` is ready for plan 01-03 (NautilusTrader submodule + editable install) and 01-08 (DSL evaluator) to build directly on top of.
- `pnpm-workspace.yaml` already lists `prisma` and `schemas` as workspace members even though neither directory exists yet — pnpm resolves the missing entries to zero packages without erroring (confirmed via `pnpm install`), so plans 01-02 and 01-04 can create those packages without a workspace-file change.
- No blockers. The one open item is cosmetic (the root-invocation pytest-scoping note above) and requires no follow-up action.

---
*Phase: 01-walking-skeleton-backtest-a-hand-written-spec-on-real-data*
*Completed: 2026-09-06*
