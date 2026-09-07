---
gsd_state_version: 1.0
current_phase: 01
current_phase_name: Walking Skeleton — Backtest a Hand-Written Spec on Real Data
status: executing
stopped_at: Completed 01-04-PLAN.md
last_updated: "2026-09-07T00:13:47.534Z"
last_activity: 2026-09-06
last_activity_desc: Phase 01 execution started
state_head: 3cb0f5e298b56518541ccc3245266a17a484ba94
progress:
  total_phases: 12
  completed_phases: 0
  total_plans: 9
  completed_plans: 4
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-05)

**Core value:** Backtest and live run the same engine, and the AI never touches credentials or
order submission.
**Current focus:** Phase 01 — Walking Skeleton — Backtest a Hand-Written Spec on Real Data

## Current Position

Phase: 01 (Walking Skeleton — Backtest a Hand-Written Spec on Real Data) — EXECUTING
Plan: 5 of 9
Status: Ready to execute
Last activity: 2026-09-06 — Phase 01 execution started

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**

- Total plans completed: 0
- Average duration: —
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:** No data yet.

*Updated after each plan completion*
**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 01 P01 | 8min | 3 tasks | 47 files |
| Phase 01 P02 | 14min | 3 tasks | 18 files |
| Phase 01 P03 | 161min | 3 tasks | 9 files |
| Phase 01 P04 | 10min | 3 tasks | 13 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table. Affecting current work:

- Stock NautilusTrader v2 (`v2.0.0rc4`), pinned commit, **no local patches**. The tenancy fork is
  shelved — there is no tenancy repair phase.
- One `LiveNode` process per tenant; isolation is a property of the process boundary.
- Python hosts the runtime; `DslEvaluator` is pure Python inside a Nautilus `Strategy`.
- Copilot approval is an `ApprovalGate` `ExecutionAlgorithm` on the `exec_algorithm_id` routing
  branch (`crates/trading/src/strategy/mod.rs:207-211`).
- The deterministic spine (Phases 1–9) ships independently. AI planes (10–12) do not start until a
  live Copilot order has been placed and reconciled.
- [Phase 01]: Task 1 package-legitimacy gate approved for all twelve [SUS]-flagged packages (checker false-positive, too-new = latest release date not founding date)
- [Phase 01]: packages/fastapi-server fully stripped of the fastapi-blog domain (beyond the four explicitly-named deletions) to avoid leaving broken imports after dependency removal; reduced to a bare /health app reserved for Phase 5
- [Phase 01]: [Phase 01, Plan 02]: engine_from_env() rewrites postgresql:// to postgresql+psycopg:// so one DATABASE_URL value works for both Prisma (TS) and SQLAlchemy Core (psycopg v3, not psycopg2)
- [Phase 01]: [Phase 01, Plan 02]: trial_recorder/record_capture manage their own transaction on the given Connection independent of caller's surrounding work, required for the D-15 crash guarantee
- [Phase 01]: [Phase 01, Plan 03]: Task 1 legitimacy gate rejected the plan's pin be9eaff8a7 (carried the tenancy patch); human named replacement pin 4692bac35bb11a25eeebb8d7af4d51c55afe53ec, verified unpatched and an ancestor of origin/develop
- [Phase 01]: [Phase 01, Plan 03]: engine/pyproject.toml overrides nautilus-trader's build to the vendored release-debugging profile via uv config-settings-package (not a vendor patch) — the stock fat-LTO release profile OOM-kills on a 32GB/10-core machine per docs/adr/0002
- [Phase 01]: [Phase 01, Plan 04]: Task 1 checkpoint resolved to Option A (hand-written engine/money.py parse_money wrapper) after a live spike found no datamodel-code-generator flag maps a pattern-string field to Decimal -- closes RESEARCH.md A3
- [Phase 01]: [Phase 01, Plan 04]: params_hash hashes raw parsed JSON values (money fields excepted, canonicalized via to_canonical_str) rather than the Pydantic model's coerced dump, since Pydantic silently coerces 5.0 to int 5 for an integer field

### Pending Todos

None yet.

### Blockers/Concerns

- **Sizing is honest, not comfortable.** ~200–315 person-weeks total (4–6 person-years); 12–18
  calendar months to the first live order for two people. If unacceptable, the lever is cutting
  Phases 10–12, not compressing 1–8.
- **Phase 11 (research committee) has no natural definition of done.** Timebox it at plan time.
- **Phase 2's `SIM-05` is open-ended.** Reproducing a published backtest is the foundation gate and
  may take weeks; expect "the shape but not the number" before it converges.
- **Do these in week one of Phase 1, out of band:** measure Rust rebuild time (PROJECT.md engine
  tripwire 3), and start the daily `exchangeInfo` cron before anything else — every day not
  snapshotting is a permanently missing row.

## Deferred Items

| Category | Item | Status | Deferred At | Milestone |
|----------|------|--------|-------------|-----------|
| *(none)* | | | | |

## Session Continuity

Last session: 2026-09-07T00:13:47.512Z
Stopped at: Completed 01-04-PLAN.md
Resume file: None
