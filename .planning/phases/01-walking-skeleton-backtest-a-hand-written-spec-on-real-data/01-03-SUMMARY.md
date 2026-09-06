---
phase: 01-walking-skeleton-backtest-a-hand-written-spec-on-real-data
plan: 03
subsystem: infra
tags: [nautilus-trader, git-submodule, rust, maturin, uv, devcontainer, adr]

# Dependency graph
requires:
  - phase: 01-01
    provides: "engine/ as a resolvable uv project (Python 3.13) that this plan extends with the editable Nautilus dependency"
provides:
  - "vendor/nautilus_trader git submodule pinned to 4692bac35bb11a25eeebb8d7af4d51c55afe53ec (v2.0.0rc4), stock/unpatched"
  - "engine/pyproject.toml editable path dependency on the submodule, plus a snapshot dependency group (httpx, sqlalchemy, psycopg[binary]) for plan 01-06's cron"
  - "engine/tests/test_engine_import.py — pinned-version assertion + stock v2 LiveNode construction proof"
  - ".devcontainer/{devcontainer.json,Dockerfile} pinning Python 3.13, Node 24, pnpm 10.34.5, uv 0.12.0, Rust 1.98.0"
  - "docs/adr/0001-shelve-tenancy-patch.md and docs/adr/0002-rust-rebuild-time-tripwire.md"
  - "archive/tenancy-768cbf3664 annotated tag, pushed and verified on the fork remote"
affects: [01-05, 01-06, 01-09]

# Actuals (#2632)
actuals:
  tokens: 12649
  tasks: 3
  commits: 3

# Tech tracking
tech-stack:
  added: [nautilus-trader (editable submodule), maturin, httpx]
  patterns:
    - "engine/pyproject.toml [tool.uv] config-settings-package overrides a vendored dependency's build profile without patching vendored source (FOUND-01-safe escape hatch for expensive default builds)"

key-files:
  created:
    - .gitmodules
    - vendor/nautilus_trader (submodule pointer)
    - engine/tests/test_engine_import.py
    - .devcontainer/devcontainer.json
    - .devcontainer/Dockerfile
    - docs/adr/0001-shelve-tenancy-patch.md
    - docs/adr/0002-rust-rebuild-time-tripwire.md
  modified:
    - engine/pyproject.toml
    - engine/uv.lock
    - .planning/phases/01-walking-skeleton-backtest-a-hand-written-spec-on-real-data/01-03-PLAN.md

key-decisions:
  - "Task 1 legitimacy gate REJECTED the plan's original pin be9eaff8a7f50ec72dd54cd0cd894fdc127e69bf (fork's multi-tenant-nautilus-runtime HEAD, a merge carrying the tenancy patch — crates/common/src/tenant.rs present, not an ancestor of origin/develop) and adopted the human-named replacement 4692bac35bb11a25eeebb8d7af4d51c55afe53ec instead (tenant.rs absent, v2.0.0rc4, ancestor of origin/develop and origin/master)"
  - "engine/pyproject.toml pins nautilus-trader's build to the submodule's own pre-existing release-debugging profile (opt-level=3, lto=false) via uv config-settings-package, because the stock [profile.release] (fat LTO, codegen-units=1) SIGKILLed after ~1h04m on this 32GB/10-core machine — a build-argument override, not a vendor patch"

patterns-established:
  - "Corrected-pin bookkeeping: when a Task 1 legitimacy gate rejects a plan's literal pin, update every operative SHA occurrence in the PLAN.md in place with an inline note, rather than leaving the plan text pointing at rejected material"

requirements-completed: [FOUND-01, FOUND-03]

coverage:
  - id: D1
    description: "NautilusTrader v2 vendored as a commit-pinned, unpatched git submodule, installed editable"
    requirement: "FOUND-01"
    verification:
      - kind: unit
        ref: "engine/tests/test_engine_import.py#test_engine_version_is_pinned"
        status: pass
      - kind: other
        ref: "git -C vendor/nautilus_trader status --porcelain (empty)"
        status: pass
    human_judgment: false
  - id: D2
    description: "A stock v2 LiveNode constructs from the pinned commit via LiveNode.builder(...).build() — no clients, no credentials, no network"
    requirement: "FOUND-01"
    verification:
      - kind: unit
        ref: "engine/tests/test_engine_import.py#test_live_node_builder_constructs"
        status: pass
    human_judgment: false
  - id: D3
    description: "snapshot dependency group installs from the committed lockfile with the trading engine absent, so plan 01-06's daily cron never compiles Rust"
    verification:
      - kind: other
        ref: "uv sync --project engine --frozen --no-install-project --only-group snapshot; find_spec('nautilus_trader') is None"
        status: pass
    human_judgment: false
  - id: D4
    description: "Tenancy patch 768cbf3664 archived on the fork remote as an annotated tag, with a written defect record"
    requirement: "FOUND-03"
    verification:
      - kind: other
        ref: "git -C vendor/nautilus_trader ls-remote --tags origin refs/tags/archive/tenancy-768cbf3664"
        status: pass
    human_judgment: false
  - id: D5
    description: "Rust rebuild-time baseline measured and recorded (PROJECT.md tripwire 3), including the headline finding that the stock release profile does not complete on this machine class"
    verification:
      - kind: other
        ref: "docs/adr/0002-rust-rebuild-time-tripwire.md (3 dated measurements + machine spec)"
        status: pass
    human_judgment: true
    rationale: "Whether the mitigated (release-debugging) build time is 'acceptable' for the two-person team's iteration loop is a judgment call the ADR presents evidence for but does not itself adjudicate."

duration: 161min
completed: 2026-09-06
status: complete
---

# Phase 1 Plan 3: Vendor NautilusTrader v2, Editable Install, Rebuild-Time Tripwire Summary

**Submodule-pinned, unpatched NautilusTrader v2 (corrected pin after a Task 1 legitimacy-gate rejection), installed editable via a build-profile override that avoids an OOM the stock release profile hits on this machine, plus the FOUND-03 tenancy archive and the PROJECT.md tripwire-3 rebuild-time baseline.**

## Performance

- **Duration:** ~161 min (2h41m) across three tasks, dominated by two full Rust workspace compiles
- **Started:** 2026-09-06T13:14:13Z (Task 1 gate resolution commit)
- **Completed:** 2026-09-06T15:55:54Z
- **Tasks:** 3
- **Files modified:** 9 (7 created, 2 modified, plus the 01-03-PLAN.md correction)

## Accomplishments

- Resolved a `blocking-human` legitimacy gate that caught the plan's literal pin carrying an unshelved tenancy patch, and re-pinned to a verified pre-patch commit instead
- Vendored `vendor/nautilus_trader` as a stock, unpatched git submodule; editable-installed it into `engine/`
- Proved the pin yields more than an importable package: a stock v2 `LiveNode` actually constructs from the builder entry point
- Declared the `snapshot` dependency group so plan 01-06's daily cron never touches Rust
- Pinned a full development environment (`.devcontainer/`) matching the submodule's own toolchain requirement
- Measured and recorded PROJECT.md's Rust-rebuild-time tripwire 3 — and found the stock configuration crosses it
- Archived the shelved tenancy branch on the fork remote with a written defect record (FOUND-03)

## Task Commits

1. **Task 1: Legitimacy gate — pinned engine commit and Rust build toolchain** - `90bd96e` (docs) — records the gate resolution and corrects every operative SHA in `01-03-PLAN.md`
2. **Task 2: Vendor the engine as a pinned submodule, install editable, pin the dev environment** - `b1e13cb` (feat)
3. **Task 3: Measure the Rust rebuild time and write both ADRs** - `06fa5c4` (docs)

_No separate "plan metadata" commit — this SUMMARY and STATE/ROADMAP updates are committed together as the final commit below._

## Files Created/Modified

- `.gitmodules` - declares the submodule at `vendor/nautilus_trader`
- `vendor/nautilus_trader` - submodule pointer, pinned commit `4692bac35bb11a25eeebb8d7af4d51c55afe53ec`
- `engine/pyproject.toml` - editable path dependency on the submodule, `maturin==1.15.0` dev dep, `snapshot` dependency group, `[tool.uv] config-settings-package` build-profile override
- `engine/uv.lock` - re-locked to reflect the new path dependency and groups
- `engine/tests/test_engine_import.py` - version + `LiveNode.builder(...).build()` construction proof
- `.devcontainer/devcontainer.json` - build args for Python 3.13, Node 24, pnpm 10.34.5, uv 0.12.0, Rust 1.98.0; persistent cargo-registry and `target/` volumes
- `.devcontainer/Dockerfile` - installs the above via nodesource/corepack, `uv python install`, and `rustup`
- `docs/adr/0001-shelve-tenancy-patch.md` - FOUND-03 defect record with file:line citations, seams worth revisiting, and the Task 1 pin-correction note
- `docs/adr/0002-rust-rebuild-time-tripwire.md` - three dated rebuild-time measurements, machine spec, and the crossed-tripwire finding
- `.planning/phases/01-walking-skeleton-backtest-a-hand-written-spec-on-real-data/01-03-PLAN.md` - every operative literal SHA updated to the corrected pin, with the gate outcome recorded inline

## Decisions Made

- **Corrected the engine commit pin at the Task 1 gate.** The plan's original pin `be9eaff8a7f50ec72dd54cd0cd894fdc127e69bf` is the fork's `multi-tenant-nautilus-runtime` branch HEAD — a merge sitting on top of the tenancy patch `768cbf3664`. `crates/common/src/tenant.rs` exists at that commit and it is not an ancestor of `origin/develop`; vendoring it would have violated FOUND-01 and D-04 in the very plan whose purpose is establishing that requirement. The human named the replacement, `4692bac35bb11a25eeebb8d7af4d51c55afe53ec` ("Pin docs.rs checks to compatible nightly") — verified at execution time to have `tenant.rs` absent, `version.json` reporting `v2.0.0rc4`, `rust-toolchain.toml` pinning `1.98.0`, and to be an ancestor of both `origin/develop` and `origin/master`. maturin==1.15.0 cleared as originally written.
- **Overrode the vendored build profile via `uv`'s per-package `config-settings-package`, not a vendor patch.** The submodule's stock `[profile.release]` (fat LTO, `codegen-units=1`, every pyo3 feature) SIGKILLed after ~1h04m of compilation on this 32GB/10-core machine. The submodule's own `Cargo.toml` already defines `release-debugging` (inherits release, `lto = false`) for exactly this situation — pinning the build to `--profile release-debugging` is a build argument, not a change to any file under `vendor/`, so `git -C vendor/nautilus_trader status --porcelain` stays empty throughout. This is documented as the headline finding of ADR 0002 rather than silently worked around.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Homebrew's `rustup` formula ships no `cargo`/`rustc` PATH proxies**
- **Found during:** Task 2 precondition check (`rustup show` reports an installed toolchain and `cargo --version` succeeds on PATH)
- **Issue:** `rustup show` worked but bare `cargo`/`rustc` were not on PATH at all; Homebrew's `rustup` formula deliberately ships no `rustup-init`-style proxy binaries.
- **First attempt (self-corrected, no lasting damage):** created symlinks from `~/.cargo/bin/{cargo,rustc,...}` directly at the Homebrew wrapper script's path. Writing a heredoc through one of those symlinks accidentally clobbered the real `libexec/bin/rustup` Mach-O binary with script text (an infinite self-exec loop), which is why `cargo --version` hung. **Fixed immediately** with `brew reinstall rustup`, verified the restored binary is a Mach-O executable again and `rustup show` is healthy, before proceeding.
- **Final fix:** wrapper scripts in `~/.cargo/bin/{cargo,rustc,rustdoc,rustfmt}` that call `"$(/opt/homebrew/bin/rustup which <tool>)" "$@"` — an explicit `rustup` subcommand invocation, not argv0-sniffing, so it is safe regardless of how the Homebrew wrapper handles its own re-exec. Persisted `export PATH="$HOME/.cargo/bin:$PATH"` in `~/.zshrc` for future sessions (did not take effect mid-session — profile is sourced once at session start, not per command — so every build command in this session explicitly exported PATH inline).
- **Files modified:** none inside the repo; `~/.cargo/bin/*` wrapper scripts and one line appended to `~/.zshrc` (outside the repository).
- **Verification:** `cargo --version` / `rustc --version` succeed on PATH; `rustup which cargo` inside `vendor/nautilus_trader` correctly resolves the `1.98.0` toolchain via the submodule's `rust-toolchain.toml` override.

**2. [Rule 1 - Bug] Stock release profile OOM-kills on this machine — see Decisions Made above**
- **Found during:** Task 2, `uv sync --project engine`
- **Fix:** `[tool.uv] config-settings-package` override to `release-debugging`, committed in `b1e13cb`.
- **Verification:** cold build completes in 37m53s with no OOM; `import nautilus_trader` succeeds; `test_engine_import.py` passes.

---

**Total deviations:** 2 auto-fixed (1 blocking — toolchain PATH, 1 bug — OOM build profile). No scope creep; both were necessary to complete Task 2 as specified.

## Issues Encountered

- A hand-invoked `cargo rustc` command (used for an initial attempt at the "warm no-op" timing measurement) produced a spurious full recompile of `nautilus_model` and its dependents. Root cause: the manual invocation lacked the `PYO3_PYTHON`/environment signature that `uv`/`maturin`'s real invocation sets, invalidating pyo3's build-script fingerprint. Discarded as non-representative; measurements 2 and 3 in ADR 0002 were both taken via the real `uv sync --project engine` path instead.
- Measurement 3 (one-touch rebuild, 34.06s) was not slower than measurement 2 (no-op, 47.55s) — a counter-intuitive result recorded honestly in the ADR rather than re-measured until it looked clean; both are well within the "under a minute" regime that matters for the tripwire conclusion.
- `packages/fastapi-server` and `engine/tests/persistence/*` tests hang waiting on a Postgres connection when Docker is not running locally — pre-existing from plan 01-02, out of this plan's scope, not touched. `engine/tests/dsl` and `engine/tests/test_engine_import.py` (the tests this plan owns) were run scoped to avoid the collision noted in the orchestrator's reminder (`engine/tests` and `packages/fastapi-server/tests` both import as `tests`).

## User Setup Required

None beyond what the plan's `user_setup` already named (rustup install, GitHub push access to the fork) — both were already present on this machine; push access was exercised successfully (submodule fetch/push, archive tag push).

## Next Phase Readiness

- `vendor/nautilus_trader` is available for plan 01-05's adapter work; `MIGRATION_V2.md` and the exact `LiveNode.builder(...)` signature were read and used directly (not from training-data memory) per D-CONTEXT requirement.
- `engine/pyproject.toml` and `engine/uv.lock` are shared with plan 01-04, which runs next on this same working tree; edits here were additive (new dependency, new group, new `[tool.uv]` table) and should layer cleanly.
- The `release-debugging` build-profile override is the one thing a future contributor could accidentally undo (e.g. "switching back to release for perf") without realizing it reintroduces the OOM — flagged prominently in ADR 0002 for exactly that reason.
- No blockers for 01-04/01-05/01-06.

---
*Phase: 01-walking-skeleton-backtest-a-hand-written-spec-on-real-data*
*Completed: 2026-09-06*

## Self-Check: PASSED

All 9 created/modified files verified present on disk; all 3 task commits (`90bd96e`, `b1e13cb`, `06fa5c4`) verified in git history.
