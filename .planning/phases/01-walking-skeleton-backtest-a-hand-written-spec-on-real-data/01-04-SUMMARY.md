---
phase: 01-walking-skeleton-backtest-a-hand-written-spec-on-real-data
plan: 04
subsystem: contracts
tags: [json-schema, codegen, pydantic, datamodel-code-generator, json-schema-to-typescript, decimal, turbo]

# Dependency graph
requires:
  - phase: 01-01
    provides: "engine/ as a resolvable uv project with dsl/ and tests/ subpackages; pnpm-workspace.yaml already listing schemas as a workspace member"
provides:
  - "schemas/strategy-spec.v1.json -- the versioned StrategySpec contract (D-06, FOUND-04), bounded to exactly the D-26 SMA crossover"
  - "schemas/scripts/generate.mjs -- the two-generator codegen step (TypeScript + Pydantic v2), with --check drift detection"
  - "engine/package.json declaring \"@repo/schemas\": \"workspace:*\" -- the Turbo ^build graph edge that regenerates both languages before @repo/engine's own tasks run, proven by a fresh-clone (deleted generated dirs) rebuild"
  - "engine/money.py -- the wire/internal money boundary: Money (strict Decimal), parse_money(), to_canonical_str(), assert_no_floats(), MONEY_SCALE=8"
  - "engine/dsl/spec.py -- StrategySpec (re-exported), load_spec() (shape + semantic validation), params_hash() (canonical SHA-256 hash), MONEY_FIELD_NAMES"
  - "docs/adr/0003-decimal-string-codegen.md -- the recorded Option A decision, closing RESEARCH.md assumption A3"
  - "schemas/guards/money-guard.stub.{test.ts,sql} -- inert D-07 TypeScript/SQL guards, real in Phase 4"
affects: [01-05, 01-06, 01-08, 01-09]

# Actuals (#2632)
actuals:
  tokens: 9863
  tasks: 3
  commits: 3

# Tech tracking
tech-stack:
  added: [json-schema-to-typescript, datamodel-code-generator (already a dev dep, first real use)]
  patterns:
    - "Wire/internal money boundary split: parse_money() is the only route from a decimal string to Decimal; Money's strict=True config rejects a string in Python mode -- two contracts, tested separately, never conflated"
    - "params_hash canonicalizes ONLY money fields (via money.to_canonical_str); every other field hashes over its raw parsed JSON value, so a real value change (5 -> 6) changes the hash while pure formatting differences (whitespace, key order) do not"
    - "--disable-timestamp on datamodel-codegen invocations, required for generate.mjs's --check mode to produce a reproducible diff run-to-run"
    - "Schema-walking drift test (test_money_field_name_list_matches_schema) asserts the hand-maintained MONEY_FIELD_NAMES set matches every money-patterned field in the schema -- closes ADR-0003 Option A's one stated weakness"

key-files:
  created:
    - docs/adr/0003-decimal-string-codegen.md
    - schemas/package.json
    - schemas/strategy-spec.v1.json
    - schemas/README.md
    - schemas/scripts/generate.mjs
    - schemas/guards/money-guard.stub.test.ts
    - schemas/guards/money-guard.stub.sql
    - engine/money.py
    - engine/dsl/spec.py
    - engine/tests/dsl/test_spec_contract.py
    - engine/tests/test_money_guard.py
  modified:
    - engine/package.json
    - pnpm-lock.yaml

key-decisions:
  - "Task 1 checkpoint:decision resolved to Option A (hand-written engine/money.py wrapper) after a live spike: datamodel-codegen 0.76.2's --help has no flag mapping a pattern-string field to Decimal (--use-decimal-for-multiple-of is keyed to type:number+multipleOf only); confirmed by generating both languages from a throwaway 3-field schema and quoting both emitted types into ADR-0003. Closes RESEARCH.md assumption A3."
  - "[Rule 3 - Blocking] engine/money.py, formally Task 3's file, was written and committed as part of Task 2's commit: dsl/spec.py's params_hash cannot canonicalize money fields without it, so Task 2 could not function without Task 3's module existing first. Written to already satisfy all of Task 3's acceptance criteria; Task 3's own commit added only the guard test suite and the TS/SQL stubs."
  - "params_hash hashes the spec's RAW parsed JSON values (money fields excepted, which route through to_canonical_str), not the Pydantic model's coerced model_dump() -- verified empirically that Pydantic's lax-mode validation silently coerces a float 5.0 to int 5 for an integer field (and strict mode rejects it outright), so a model-dump-based hash could not distinguish '5' from '5.0' as the plan's Test 4 example asked. Hashing the raw parsed value preserves that distinction for every non-money field while still normalizing money precision, which is the intended asymmetry: strict elsewhere, semantically equal only where D-07 explicitly asks for it."
  - "generate.mjs's datamodel-codegen invocation adds --disable-timestamp (not in the plan text) -- without it, --check always reports drift because every invocation embeds a fresh timestamp comment, defeating the drift check's purpose."

patterns-established:
  - "Pattern 3: a codegen script's --check mode regenerates into a scratch temp directory and diffs against whatever is currently on disk at the real output paths -- never against a committed copy, since the outputs are gitignored build artifacts (D-06)."

requirements-completed: [FOUND-04, FOUND-09]

coverage:
  - id: D1
    description: "Task 1 checkpoint:decision -- spike run, both generated type declarations quoted verbatim into ADR-0003, human selected Option A"
    verification: []
    human_judgment: true
    rationale: "A checkpoint:decision is explicitly a human choice among options the spike's evidence narrows but does not itself resolve automatically."
  - id: D2
    description: "schemas/strategy-spec.v1.json is the source of truth: $id, spec_version const \"1\", additionalProperties:false at every level, fast_period/slow_period as positive integers with no cross-property comparison, trade_size as a money-pattern string"
    requirement: "FOUND-04"
    verification:
      - kind: other
        ref: "pnpm --filter @repo/schemas run build (both generated files produced)"
        status: pass
      - kind: other
        ref: "grep -cE 'trade_size\\??: *number' schemas/generated/ts/strategy-spec.d.ts -> 0"
        status: pass
    human_judgment: false
  - id: D3
    description: "Turbo ^build graph edge: engine/package.json declares @repo/schemas as a workspace dependency, so a clean checkout with both generated directories deleted regenerates them via `pnpm turbo run build --filter=@repo/engine` with no manual step"
    requirement: "FOUND-04"
    verification:
      - kind: other
        ref: "rm -rf engine/generated schemas/generated && pnpm turbo run build --filter=@repo/engine && test -f engine/generated/strategy_spec.py"
        status: pass
      - kind: other
        ref: "(cd engine && uv run python -c \"import dsl.spec\") -- succeeds after the above"
        status: pass
    human_judgment: false
  - id: D4
    description: "dsl/spec.py: load_spec rejects empty/{}/null/malformed shape, rejects an inverted window pair semantically (SpecSemanticError), params_hash is key-order independent and formatting independent while remaining sensitive to real value changes and canonicalizing money precision"
    requirement: "FOUND-04"
    verification:
      - kind: unit
        ref: "uv run --project engine pytest engine/tests/dsl/test_spec_contract.py -q -> 11 passed"
        status: pass
    human_judgment: false
  - id: D5
    description: "engine/money.py: Money (strict Decimal) rejects float and string in Python mode; parse_money is the sole wire route; 8dp accepted/9dp rejected; banker's rounding explicit; assert_no_floats walker; zero float() calls; no reference to Pydantic's JSON-mode validation entry point"
    requirement: "FOUND-09"
    verification:
      - kind: unit
        ref: "uv run --project engine pytest engine/tests/test_money_guard.py -q -> 10 passed"
        status: pass
      - kind: other
        ref: "grep -cE '\\bfloat\\(' engine/money.py -> 0; grep -c 'ROUND_HALF_EVEN' engine/money.py -> 3; grep -c model_validate_json engine/money.py -> 0"
        status: pass
    human_judgment: false
  - id: D6
    description: "TypeScript and SQL float-in-money guard stubs exist, are inert, and are not wired into any CI job or turbo task"
    requirement: "FOUND-09"
    verification:
      - kind: other
        ref: "test -f schemas/guards/money-guard.stub.test.ts && test -f schemas/guards/money-guard.stub.sql"
        status: pass
    human_judgment: false

# Metrics
duration: 10min (execution) + checkpoint wait for Task 1 human decision
completed: 2026-09-07
status: complete
---

# Phase 1 Plan 4: StrategySpec Schema, Two-Generator Codegen, Money Guard Summary

**One versioned JSON Schema now drives both a generated Pydantic model and a generated TypeScript type via a Turbo graph edge (not a remembered step); a strict wire/internal money boundary (`parse_money`/`Money`) makes a float reaching a money field fail the Python test suite, with TypeScript and SQL guards landing as honest, inert stubs for Phase 4.**

## Performance

- **Duration:** ~10 min of active execution across three tasks (plus a checkpoint pause awaiting the Task 1 human decision, not counted as execution time)
- **Tasks:** 3
- **Files modified:** 13 (11 created, 2 modified, excluding `pnpm-lock.yaml`'s dependency-add churn)

## Accomplishments

- Resolved the Task 1 `checkpoint:decision` on real evidence, not reasoning alone: ran `datamodel-codegen --help` in full (no flag maps a pattern-string field to `Decimal`), generated both languages from a throwaway repro schema, and quoted both verbatim emitted types into `docs/adr/0003-decimal-string-codegen.md`. Human selected Option A. RESEARCH.md assumption A3 is now closed by direct evidence rather than left open.
- `schemas/strategy-spec.v1.json` is the versioned, bounded StrategySpec contract: `$id`, `spec_version` const `"1"`, `additionalProperties: false` at every object level, `fast_period`/`slow_period` as positive integers with the ordering rule deliberately left out of the schema (semantic-only, per D-26), and `sizing.trade_size` as an 8-decimal-place money pattern string.
- `schemas/scripts/generate.mjs` runs both generators from that one schema and its `--check` mode genuinely detects schema/generated drift by diffing a fresh scratch-directory regeneration against whatever is on disk -- required adding `--disable-timestamp` to the Pydantic invocation, since every default invocation embeds a fresh timestamp comment that would otherwise make `--check` report false drift on every run.
- The Turbo `^build` graph edge is real, not asserted: `engine/package.json` now declares `"@repo/schemas": "workspace:*"`, and deleting both `engine/generated/` and `schemas/generated/` (reproducing exactly a clean-clone state, since both are gitignored) and running `pnpm turbo run build --filter=@repo/engine` regenerates the Pydantic model and leaves `dsl.spec` importable with zero manual steps.
- `engine/money.py` gives Python a strict, testable money boundary: `parse_money()` is the one sanctioned route from a decimal string to `Decimal` (never built on Pydantic's JSON-mode validation entry point, which is a version-dependent library detail this project's money contract should not move with); `Money`'s `strict=True` config rejects a plain string in Python mode -- proven by a passing test that a string is *rejected* there, not just that a `Decimal` is accepted, so the boundary can't quietly be widened later. 10/10 tests pass, covering both boundaries, the 8/9-decimal-place edge, `"1.50"`/`"1.5"` adjacency, empty/`None` rejection, explicit banker's rounding, and a float-leak walker.
- `engine/dsl/spec.py` exposes `StrategySpec`, `load_spec()`, `params_hash()`, `SpecSemanticError`; 11/11 tests pass including a schema-walking drift test that asserts the hand-maintained money-field-name list matches the schema exactly, closing Option A's one stated weakness.
- Both D-07 guard stubs (`schemas/guards/money-guard.stub.test.ts`, `money-guard.stub.sql`) exist, are inert (skipped test / commented query), and are recorded in `.planning/WINDOWS.md` as open stub entries for ship-gate visibility, per D-07's explicit Phase-4 deferral.

## Task Commits

1. **Task 1: Spike then decide -- decimal-string codegen mechanism** - `66a8634` (docs) -- ADR-0003 written and committed after the human's `checkpoint:decision` resolution to Option A
2. **Task 2: Author the versioned schema and wire the two-generator codegen step** - `9e0bccd` (feat) -- includes `engine/money.py`, pulled forward from Task 3 as a genuine blocking dependency
3. **Task 3: The float-in-money guard -- Python real, TypeScript/SQL as stubs** - `3cb0f5e` (feat) -- guard test suite + both stubs, plus a fix to `money.py`'s docstring that self-tripped its own verify grep

**Plan metadata:** (this commit, following SUMMARY)

## Files Created/Modified

- `docs/adr/0003-decimal-string-codegen.md` -- the Task 1 decision record, both spike outputs quoted verbatim
- `schemas/package.json` -- `@repo/schemas`, `json-schema-to-typescript` dependency, `build`/`check-types` scripts
- `schemas/strategy-spec.v1.json` -- the schema (86 lines)
- `schemas/README.md` -- states the window-ordering-is-semantic-not-schema rule and the money-field decimal-string rule, both outside `engine/dsl/`'s grepped path
- `schemas/scripts/generate.mjs` -- the two-generator build/check script
- `schemas/guards/money-guard.stub.test.ts`, `schemas/guards/money-guard.stub.sql` -- inert D-07 stubs
- `engine/money.py` -- `Money`, `parse_money()`, `to_canonical_str()`, `assert_no_floats()`, `MONEY_SCALE`
- `engine/dsl/spec.py` -- `StrategySpec`, `load_spec()`, `params_hash()`, `SpecSemanticError`, `MONEY_FIELD_NAMES`
- `engine/tests/dsl/test_spec_contract.py` -- 11 tests
- `engine/tests/test_money_guard.py` -- 10 tests
- `engine/package.json` -- added `"dependencies": {"@repo/schemas": "workspace:*"}`
- `pnpm-lock.yaml` -- updated for the new `@repo/schemas` package and its `json-schema-to-typescript` dependency

## Decisions Made

- **Task 1 checkpoint:decision: Option A selected.** See Key Decisions above and ADR-0003 for the full spike evidence and rejected alternatives (Option B -- custom template directory, couples the build to an unstable internal structure; Option C -- custom base class, trades one hand-maintained list for an equivalent runtime heuristic with no net simplification).
- **`params_hash` hashes raw parsed values, not the Pydantic model's coerced dump**, for every field except money (which explicitly canonicalizes via `to_canonical_str`). This was discovered mid-implementation, not assumed: verified empirically that Pydantic's lax validation silently coerces `5.0` to `5` for an integer field (making a model-dump-based hash unable to distinguish the plan's literal Test 4 example), and that strict mode rejects `5.0` outright rather than accepting it with a different hash. The chosen design keeps every non-money field maximally hash-sensitive (any representational difference changes the hash) while money fields alone get semantic canonicalization -- the asymmetry D-07 actually asks for, not blanket normalization.
- **`--disable-timestamp` added to the `datamodel-codegen` invocation** inside `generate.mjs`, not present in the plan's literal action text -- without it, every generation embeds a fresh `# timestamp: ...` comment, making `--check`'s diff always report drift even with no schema change. Discovered by running `--check` twice in a row and observing a false-positive drift report.
- **`engine/money.py` written and committed a task early** (see Deviations) -- a genuine ordering dependency the plan's task split didn't account for, not a scope expansion.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `engine/money.py` created in Task 2's commit, not Task 3's**
- **Found during:** Task 2, writing `dsl/spec.py`'s `params_hash`
- **Issue:** The plan's action text for Task 2 explicitly requires `params_hash` to serialize "money values as their canonical decimal strings via `engine.money`" -- but `engine/money.py` is listed only in Task 3's `<files>`. Task 2 cannot function without a module Task 3 hasn't written yet.
- **Fix:** Wrote `engine/money.py` in full during Task 2 (satisfying all of Task 3's stated acceptance criteria up front), and committed it as part of Task 2's commit with an explicit note in the commit message. Task 3's own commit then added only the test suite (`engine/tests/test_money_guard.py`) and the TS/SQL stubs, verifying the already-written module rather than re-implementing it.
- **Files modified:** `engine/money.py` (created in commit `9e0bccd`, Task 2's commit)
- **Verification:** Task 3's full 10-test suite passes against the module as written in Task 2, with no changes needed beyond the docstring fix below.
- **Committed in:** `9e0bccd` (Task 2), test suite added in `3cb0f5e` (Task 3)

**2. [Rule 1 - Bug] `money.py`'s docstring self-tripped its own verify gate**
- **Found during:** Task 3, running the plan's `grep -cE '\bfloat\(' engine/money.py` verify command
- **Issue:** The module docstring's sentence "`float()` never appears on any money path in this module" contains the literal substring `float(`, matching the grep pattern meant to catch an actual call to the built-in and reporting `1` instead of the required `0` -- the exact self-referential-grep-gate bug already seen once in Plan 01-02 (`autoload_with` in a docstring).
- **Fix:** Reworded to "this module never casts a value to the built-in floating-point type on any money path" -- same meaning, no literal `float(` substring.
- **Files modified:** `engine/money.py`
- **Verification:** `grep -cE '\bfloat\(' engine/money.py` -> `0`.
- **Committed in:** `3cb0f5e` (Task 3)

**3. [Rule 3 - Blocking] `--disable-timestamp` added to the generator invocation**
- **Found during:** Task 2, first run of `pnpm --filter @repo/schemas run check-types`
- **Issue:** `datamodel-codegen`'s default output embeds a `# timestamp: <current time>` header comment, so two consecutive generations of byte-identical schema content produce byte-different files -- `--check`'s whole purpose (detecting real drift) was defeated by this false positive on every invocation.
- **Fix:** Added `--disable-timestamp` to the `datamodel-codegen` invocation in `generate.mjs`.
- **Files modified:** `schemas/scripts/generate.mjs`
- **Verification:** Ran `build` then `check-types` back to back -- `check-types` now reports "generated output matches the schema" instead of false drift.
- **Committed in:** `9e0bccd` (Task 2)

---

**Total deviations:** 3 auto-fixed (1 blocking task-ordering dependency, 1 self-referential-grep bug, 1 blocking codegen-reproducibility fix). No scope creep beyond what each task's own stated requirements demanded; no Rule 4 checkpoints raised.

## Issues Encountered

- The plan's literal Task 2 verify command `uv run --project engine python -c "import engine.dsl.spec"` (invoked from repo root) fails with `ModuleNotFoundError: No module named 'generated'` -- **this is expected, not a defect**, and matches the exact convention already established and documented in Plan 01-01's SUMMARY: `engine/` has no top-level `__init__.py` (a deliberate choice unchanged by this plan), so `dsl/spec.py`'s internal bare imports (`from generated.strategy_spec import StrategySpec`, `from money import to_canonical_str`) only resolve when `engine/` itself is on `sys.path` -- true when invoked via `cd engine && uv run ...` (what `pnpm --filter @repo/engine` / `turbo run` actually do, and what the acceptance criterion's *real* fresh-clone verification exercises), and true inside pytest regardless of process `cwd` (pytest's own rootdir-based `sys.path` insertion is independent of `os.getcwd()`). Verified both the pytest-based check (`uv run --project engine pytest engine/tests/dsl/test_spec_contract.py -q`, works identically from any cwd) and the real Turbo path (`pnpm turbo run build --filter=@repo/engine` then `cd engine && uv run python -c "import dsl.spec"`, succeeds) pass. No fix applied -- introducing `engine/__init__.py` to make the literal `engine.dsl.spec` form work would be a Rule 4 architectural change rippling across every other already-committed module's import convention (`persistence.trials`, `persistence.snapshots`, etc. from Plan 01-02), for a purely cosmetic gain.
- `pnpm test` (the full monorepo suite) was run once at the end to confirm nothing regressed: 39/39 tests pass in `@repo/engine` (including the 3 pre-existing scaffold tests, 10 persistence tests from Plan 01-02, and 2 `test_engine_import` tests from Plan 01-03 -- confirming the Nautilus submodule import still works and no rebuild was triggered by this plan's `uv sync --frozen`), plus `@repo/fastapi-server`'s 1 test (cache hit). Docker/Postgres was already running locally, so persistence tests did not hang.

## User Setup Required

None -- no external service configuration required. `json-schema-to-typescript` installed cleanly via `pnpm install` from the existing npm registry access.

## Next Phase Readiness

- `schemas/strategy-spec.v1.json`, `engine/dsl/spec.py`, and `engine/money.py` are ready for Plan 01-05 (the tracer) to import directly (`from dsl.spec import load_spec, params_hash` and `from money import parse_money, to_canonical_str, assert_no_floats`) when building the first real backtest CLI run and its persistence write.
- `engine/adapters/dsl_strategy.py` (not yet written -- a later plan) is the one file permitted to import both `dsl.evaluator` (not yet written either) and `nautilus_trader`; nothing in this plan touched `engine/adapters/`.
- The `MONEY_FIELD_NAMES` drift test means any future schema change adding a money-patterned field will fail the build loudly if `dsl/spec.py`'s hand-maintained set isn't updated to match -- this is the intended behavior, not a bug to silence.
- Two open stub entries now exist in `.planning/WINDOWS.md` (the TS and SQL money guards) -- both are D-07's explicit, deliberate Phase-4 deferral, not a phase-1 gap; the ship gate will see them as open until Phase 4 makes them real.
- No blockers for 01-05/01-06/01-08/01-09.

## Self-Check: PASSED

All 11 created files verified present on disk (`docs/adr/0003-decimal-string-codegen.md`,
`schemas/package.json`, `schemas/strategy-spec.v1.json`, `schemas/README.md`,
`schemas/scripts/generate.mjs`, `schemas/guards/money-guard.stub.test.ts`,
`schemas/guards/money-guard.stub.sql`, `engine/money.py`, `engine/dsl/spec.py`,
`engine/tests/dsl/test_spec_contract.py`, `engine/tests/test_money_guard.py`). All 3 cited
commit hashes (`66a8634`, `9e0bccd`, `3cb0f5e`) verified present in `git log`. Both gitignored
generated directories (`engine/generated/`, `schemas/generated/`) confirmed absent from
`git status --porcelain` and confirmed `!!`-ignored via `git status --short --ignored=matching`.
Full monorepo `pnpm test` run: 39/39 `@repo/engine` tests pass, 1/1 `@repo/fastapi-server` test
passes.

---
*Phase: 01-walking-skeleton-backtest-a-hand-written-spec-on-real-data*
*Completed: 2026-09-07*
