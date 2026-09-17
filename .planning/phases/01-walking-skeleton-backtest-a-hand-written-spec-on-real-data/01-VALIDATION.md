---
phase: "01"
slug: "walking-skeleton-backtest-a-hand-written-spec-on-real-data"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-09-06"
---

# Phase 01 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (Python 3.13, `engine/` uv project) |
| **Config file** | `engine/pyproject.toml` → `[tool.pytest.ini_options]` — **does not exist yet**; plan 01-01 Task 3 creates it |
| **Quick run command** | `uv run --project engine pytest engine/tests/dsl -q` |
| **Full suite command** | `uv run --project engine pytest engine/tests -q` |
| **Pipeline command** | `pnpm turbo run test lint check-types` (D-08 — the single CI entry point, added by plan 01-09) |
| **Estimated runtime** | quick: < 1 second (this is a *requirement*, not an observation — success criterion 3 names it). Full: ~90-180 seconds once the tracer's live-network and Postgres-backed tests exist. |

There is no JavaScript/TypeScript test framework in this phase. The two D-07 guard stubs
(`schemas/guards/money-guard.stub.test.ts`, `schemas/guards/money-guard.stub.sql`) are
deliberately inert and wired into no runner until Phase 4.

---

## Sampling Rate

- **After every task commit:** `uv run --project engine pytest engine/tests/dsl -q`
- **After every plan wave:** `uv run --project engine pytest engine/tests -q`
- **After wave 4:** `pnpm turbo run test lint check-types`
- **Before `/gsd-verify-work`:** full suite green, plus the elapsed-days wait described under
  Manual-Only Verifications
- **Max feedback latency:** 1 second for the pure suite, 180 seconds for the full suite

Two deselect markers keep the loop fast: tests that hit the network and tests that need the
compose Postgres are marked so `-m "not network and not db"` gives a pure-logic run.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 1 | FOUND-05, FOUND-06 | T-01-SC | Human vets 12 `[SUS]` packages before any install-time code executes | checkpoint (blocking-human) | — (human gate) | N/A | ⬜ pending |
| 1-01-02 | 01 | 1 | FOUND-05, FOUND-06 | T-01-01 | Generated contract artifacts cannot be committed | structural | `pnpm install --lockfile-only` | ❌ W0 | ⬜ pending |
| 1-01-03 | 01 | 1 | FOUND-05, FOUND-06 | T-01-01 | `engine/dsl/` exists and is already engine-free | unit | `uv run --project engine pytest engine/tests/dsl -q` | ❌ W0 | ⬜ pending |
| 1-02-01 | 02 | 2 | VALID-01, DATA-03 | T-01-07 | DB-side UUID defaults; explicit `@map` on every new field; no dedup mechanism at either snapshot level | structural | `pnpm --filter @quant/prisma exec prisma validate` | ❌ W0 | ⬜ pending |
| 1-02-02 | 02 | 2 | VALID-01, DATA-03 | T-01-05 | Migration applied to a live DB; physical column names confirmed snake_case from `information_schema` | integration | `pnpm --filter @quant/prisma exec prisma migrate deploy` | ❌ W0 | ⬜ pending |
| 1-02-03 | 02 | 2 | VALID-01, DATA-03 | T-01-03, T-01-04, T-01-24b | Parameterized Core inserts only; a crashed run still leaves a counted row; a capture is atomic with one shared instant; two-way schema parity | integration | `uv run --project engine pytest engine/tests/persistence -q` | ❌ W0 | ⬜ pending |
| 1-03-01 | 03 | 2 | FOUND-01 | T-01-SC2 | Human vets the build backend and the exact commit pin before any build | checkpoint (blocking-human) | — (human gate) | N/A | ⬜ pending |
| 1-03-02 | 03 | 2 | FOUND-01 | T-01-08 | Vendored source is stock; a stock v2 node constructs from the pin; the snapshot group installs without the trading engine | integration | `uv run --project engine pytest engine/tests/test_engine_import.py -q` | ❌ W0 | ⬜ pending |
| 1-03-03 | 03 | 2 | FOUND-03 | T-01-10 | Rebuild-time baseline recorded as three dated numbers; archive tag verified on the fork remote; submodule still clean afterwards | doc assertion | `git -C vendor/nautilus_trader ls-remote --tags origin 'refs/tags/archive/tenancy-768cbf3664'` | ❌ W0 | ⬜ pending |
| 1-04-01 | 04 | 2 | FOUND-04, FOUND-09 | T-01-13 | Codegen mechanism chosen on real generated output, not on assumption | checkpoint (decision) | — (human gate, spike evidence required) | N/A | ⬜ pending |
| 1-04-02 | 04 | 2 | FOUND-04 | T-01-11, T-01-13 | Empty/`{}`/`null` spec rejected; inverted window pair rejected semantically; generated TS money type is `string`; clean-clone codegen runs as a graph edge | unit | `uv run --project engine pytest engine/tests/dsl/test_spec_contract.py -q` | ❌ W0 | ⬜ pending |
| 1-04-03 | 04 | 2 | FOUND-09 | T-01-12 | A float reaching a money field raises; wire and internal money boundaries separately pinned; no `float(` on any money path | unit | `uv run --project engine pytest engine/tests/test_money_guard.py -q` | ❌ W0 | ⬜ pending |
| 1-05-01 | 05 | 3 | DATA-01, DATA-02, DATA-06, SIM-01, SIM-04, FOUND-05, FOUND-06 | T-01-15, T-01-16, T-01-17 | Checksum hard-fail with no fallback; zip entries path-checked; close-time bars; dual-import set is exactly the adapter | integration (tracer, end-to-end) | `uv run --project engine pytest engine/tests/tracer/test_end_to_end.py -q` | ❌ W0 | ⬜ pending |
| 1-05-02 | 05 | 3 | SIM-02, VALID-01 | T-01-18 | Every exit path after recorder entry leaves a trials row; hash excludes per-process fields | integration | `uv run --project engine pytest engine/tests/tracer/test_reproducibility.py -q` | ❌ W0 | ⬜ pending |
| 1-06-01 | 06 | 3 | DATA-03 | T-01-21 | Credential in a secrets manager from day one, not a committed file | checkpoint (decision) | — (human gate) | N/A | ⬜ pending |
| 1-06-02 | 06 | 3 | DATA-03 | T-01-22, T-01-24, T-01-24b | Raw payload preserved; capture written atomically with one shared instant; no upsert/dedup; decimals not floats | unit | `uv run --project engine pytest engine/tests/data/test_exchange_info.py -q` | ❌ W0 | ⬜ pending |
| 1-06-03 | 06 | 3 | DATA-03 | T-01-23 | No `continue-on-error` — a dead cron shows red; the run is identified by returned id, not by "most recent" | integration (CI) | `gh run watch "$RUN_ID" --exit-status` (run id captured after `gh workflow run`, bounded by `timeout 900`) | ❌ W0 | ⬜ pending |
| 1-07-01 | 07 | 4 | DATA-01, DATA-06 | T-01-26, T-01-27, T-01-28 | Per-file unit detection; no bulk extract-all; verified-digest resume | unit | `uv run --project engine pytest engine/tests/data/test_binance_vision.py -q` | ❌ W0 | ⬜ pending |
| 1-07-02 | 07 | 4 | DATA-02 | T-01-29, T-01-30 | CI is read-only on the shared catalog | integration | `uv run --project engine pytest engine/tests/data/test_catalog.py -q` | ❌ W0 | ⬜ pending |
| 1-08-01 | 08 | 4 | FOUND-05 | T-01-33 | Bounded deque sized by the schema-constrained slow window | unit | `uv run --project engine pytest engine/tests/dsl -q` | ❌ W0 | ⬜ pending |
| 1-08-02 | 08 | 4 | FOUND-06, SIM-04 | T-01-32, T-01-34 | Purity grep over `engine/dsl/` + dual-import set equals the adapter, enforced in CI and in the suite | structural | `uv run --project engine pytest engine/tests/dsl/test_purity_boundary.py -q` | ❌ W0 | ⬜ pending |
| 1-09-01 | 09 | 4 | SIM-02, VALID-01 | T-01-38 | Canonical form audited by negative assertion, not by reasoning; artifact set asserted per plotted/unplotted case | integration | `uv run --project engine pytest engine/tests/determinism -q` | ❌ W0 | ⬜ pending |
| 1-09-02 | 09 | 4 | FOUND-09 | T-01-36, T-01-39, T-01-40 | Rust cache keyed on the submodule SHA; money guard demonstrably runs in CI | integration (CI) | `pnpm turbo run test lint check-types` | ❌ W0 | ⬜ pending |
| 1-09-03 | 09 | 4 | SIM-02 | T-01-37 | The two-machine claim is evidenced, not asserted | checkpoint (blocking-human) | — (human gate, two machines) | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

Every `❌ W0` above resolves the moment plan 01-01 Task 3 lands the pytest harness — the marker
means "no test framework exists for `engine/` yet", not "this task has no automated verification".
The three checkpoints are the only tasks in this phase with no automated command, and all three
are `blocking-human` or `decision` gates where a machine check would be the wrong instrument.

---

## Wave 0 Requirements

Wave 0 for this phase is plan 01-01 Task 3, which is the first executable work in the phase.
Nothing under `engine/` exists before it.

- [ ] `engine/pyproject.toml` — `[tool.pytest.ini_options]` with `testpaths = ["tests"]`; no test framework exists for the engine today
- [ ] `engine/tests/conftest.py` — the `synthetic_bars` fixture (≥40 decimal-string bars, strictly increasing nanosecond timestamps, crossing a 5/20 SMA pair in both directions), importing only the standard library
- [ ] `engine/tests/dsl/` — the pure suite directory, runnable with no engine installed
- [ ] `engine/tests/dsl/test_scaffold_smoke.py` — proves the harness collects and runs
- [ ] `engine/tests/data/fixtures/klines_ms_era.csv` and `klines_us_era.csv` — the 13-digit and 16-digit timestamp samples (plan 01-07 Task 1); parsing must be testable with no network access
- [ ] `engine/tests/data/fixtures/klines_corrupt.zip` + `.CHECKSUM` — so checksum hard-fail is testable offline
- [ ] `engine/tests/data/fixtures/exchange_info_sample.json` — trimmed from the real fixture already in the vendored checkout (plan 01-06 Task 2)
- [ ] `.github/workflows/dsl-purity.yml` — a CI job that installs the engine project **without** the vendored engine and asserts the import fails there (plan 01-08 Task 2). This is the only way to prove success criterion 3's "no engine present" claim; a test that merely avoids the import while the package sits importable proves avoidance, not absence.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Package legitimacy for 12 `[SUS]`-flagged packages | FOUND-04, FOUND-09, VALID-01 | A registry page's legitimacy is a human judgement about provenance; the checker's `too-new` signal is a known false positive here and only a person can say so responsibly | Plan 01-01 Task 1 — open each PyPI/npm page, confirm the canonical repo and a multi-year release history |
| Legitimacy of the build backend and the exact engine commit pin | FOUND-01 | The engine is the platform's trust anchor; confirming the pin is a point on upstream history and not a divergent local edit needs a human reading the fork | Plan 01-03 Task 1 |
| FOUND-01 scope, if node construction proves to need live infrastructure | FOUND-01 | Whether to amend the requirement wording or move it to Phase 5 is a scope judgement, not a test outcome | Plan 01-03 Task 2 — if `test_live_node_builder_constructs` must be skipped, the SUMMARY names the required infrastructure and flags the requirement wording for a human decision |
| Codegen mechanism for string-typed decimal fields | FOUND-04, FOUND-09 | RESEARCH.md open question 1 — no documented path was found; the answer is read off real generated output | Plan 01-04 Task 1, with the two emitted type declarations quoted into ADR-0003 |
| Hosted store and secrets manager selection | DATA-03 | One-way for non-backfillable history; a machine cannot weigh account structure against time-to-first-row | Plan 01-06 Task 1 |
| Byte-identical **canonical result bytes and hash** on two machines | SIM-02 | Success criterion 2 is a two-machine claim; no single-machine test can close it, and a hash that silently includes a hostname or a path passes locally forever | Plan 01-09 Task 3 — run the reference backtest on machine A and on a genuinely different machine, compare `hash.txt` only. The `.parquet` bytes are outside the contract by design; the ROADMAP wording is broader than this and is flagged in that task for a human to amend |
| Gapless daily snapshot count | DATA-03 | Inherently time-based: a claim about consecutive calendar days cannot be satisfied on the day the code merges, no matter how correct the code is | After plan 01-06 ships, run `SELECT capture_date, status, expected_symbol_count, actual_symbol_count FROM snapshot_capture ORDER BY capture_date` and confirm no missing date and no non-complete or short capture. The child-side `SELECT captured_at::date AS d, count(*) FROM symbol_listing_snapshot GROUP BY d ORDER BY d` shows volume but cannot prove completeness. Plan 01-06 is scheduled in wave 3 specifically so this waiting period overlaps waves 3-4 rather than following them |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or a documented human-gate reason — 20 of 23 tasks carry automated commands; the 3 exceptions are checkpoints
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify — longest gap is 1 (each checkpoint is immediately followed by an automated task)
- [ ] Wave 0 covers all `❌ W0` references
- [ ] No watch-mode flags — every command above is single-shot
- [ ] Feedback latency < 180s for the full suite, < 1s for the pure suite
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
