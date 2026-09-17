# Phase 1: Walking Skeleton — Backtest a Hand-Written Spec on Real Data - Context

**Gathered:** 2026-09-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Real Binance spot history is ingested from `data.binance.vision` with checksum verification into
a `ParquetDataCatalog`; one hand-written JSON `StrategySpec` runs through a pure-Python
`DslEvaluator` (zero Nautilus imports) via a single `DslStrategy` adapter inside stock
NautilusTrader v2; the run emits an equity curve and trade list that are byte-identical on re-run.
Two non-backfillable histories start now: the daily `exchangeInfo` snapshot (`DATA-03`) and the
trials table (`VALID-01`).

Also in scope, per the roadmap: archive the tenancy branch with a written record (`FOUND-03`),
and take the tripwire-3 Rust rebuild-time measurement in week one.

**Not in this phase:** validation statistics (Phase 3), any control-plane UI or auth flow
(Phase 4), paper or live trading (Phase 5+), any LLM call whatsoever (Phase 10+).

</domain>

<decisions>
## Implementation Decisions

### Repository Structure

- **D-01:** Full restructure of the Turborepo template now, rather than adding alongside it. The
  tree should match the architecture from commit one instead of being renamed under load later.
  — **Reversibility:** costly — a later restructure rewrites every import path, the turbo task
  graph, and both Dockerfiles once real code exists.
- **D-02:** Top-level `engine/` as a uv project on Python 3.13, containing `dsl/` (pure —
  `spec.py`, `evaluator.py`), `adapters/dsl_strategy.py` (the sole file importing both
  `DslEvaluator` and Nautilus), `data/`, `cli/`, `tests/`. The pnpm/turbo root is retained and
  orchestrates Python via a thin `engine/package.json` shim delegating `test`/`lint` to
  `uv run pytest` / `ruff`. Shared JSON Schema lives in top-level `schemas/`.
  — **Reversibility:** one-way — success criterion 3 greps the literal path `engine/dsl/`, so
  moving it changes a published acceptance criterion, and every downstream phase's grep-enforced
  lock-in check is anchored to it.
- **D-03:** `packages/fastapi-server` is kept but stripped of the `fastapi-blog` template domain
  (posts/users routers, JWT auth, aiosqlite) and reserved as the future supervisor surface for
  the per-tenant `LiveNode` processes in Phase 5. It has no role in Phase 1 itself.
- **D-04:** NautilusTrader v2 is consumed as a **git submodule pinned to an exact commit, installed
  editable** — not as a published wheel. Rationale: PROJECT.md tripwire 3 requires measuring Rust
  rebuild time, which a wheel never exercises; and the upstream source paths PROJECT.md cites
  (`crates/trading/src/strategy/mod.rs:207-211`, `crates/live/src/tenant.rs:259-262`,
  `common/src/tenant.rs:170-177`, `python/redis/cache.rs:335-336`) stay readable in-tree.
  **Consequence for planning:** every developer and every CI job needs a Rust toolchain, and cold
  builds are slow. Pin the commit, not the `v2.0.0rc4` tag.
  — **Reversibility:** reversible — swapping to a wheel later is a lockfile change.
- **D-05:** `FOUND-03` archive record is `docs/adr/0001-shelve-tenancy-patch.md`, carrying the
  defect evidence and file:line citations already in PROJECT.md Key Decisions. The branch is
  preserved as an `archive/tenancy-768cbf3664` tag on our fork.
- **D-06:** `FOUND-04` — the hand-written `schemas/strategy-spec.v1.json` is the source of truth.
  Pydantic models are generated with `datamodel-code-generator` and TS types with
  `json-schema-to-typescript`, both into gitignored directories at build time. Neither language is
  authoritative, so neither can drift.
  — **Reversibility:** costly — reversing to a Pydantic-first model means rewriting the schema by
  hand and re-deriving TS, and any spec already persisted was validated against the generated shape.
- **D-07:** `FOUND-09` float-in-money guard covers **Python, TypeScript, and SQL** (Decimal /
  string-or-bigint / NUMERIC-or-TEXT respectively). Rust is stock upstream and not ours to test.
  Only the Python guard is buildable in Phase 1; the TS and SQL guards land as stubs and become
  real in Phase 4.
- **D-08:** CI is **one turbo pipeline** — `turbo run test lint check-types` is the single entry
  point, with the engine shim delegating to uv. **Planner note:** combined with D-04 this means the
  CI image needs Node, pnpm, Python 3.13 and a Rust toolchain; expect a slow cold image and plan
  submodule/Rust caching deliberately.
- **D-09:** Prisma is extracted into its own workspace package that Phase 1 genuinely depends on
  (it owns the `trials` and `symbol_listing_snapshot` migrations). `apps/web` and `apps/server` are
  **removed from the workspace** until Phase 4, so nothing dormant needs maintaining and Next.js
  will not be several majors stale when it is finally needed.
- **D-10:** A single root `docker-compose.yml` owns Postgres, replacing the two the template ships.
  A devcontainer pins Python 3.13, Node, pnpm and the Rust toolchain — making success criterion 2
  ("byte-identical on two machines") an environment guarantee rather than a hope.

### Persistence — trials and exchangeInfo snapshots

- **D-11:** Postgres exists from Phase 1, with **Prisma as the sole schema owner**. `trials` and
  `symbol_listing_snapshot` are declared in `schema.prisma`; Python writes into the
  Prisma-migrated tables via SQLAlchemy Core. One schema owner forever, no arbitration rule needed.
  **Planner note:** this makes an otherwise pure-Python phase depend on the TS toolchain to run a
  migration — sequence that dependency explicitly.
  — **Reversibility:** one-way — moving schema ownership to alembic later requires reconciling two
  migration histories against a database already holding non-backfillable rows.
- **D-12:** The `DATA-03` cron is a **scheduled GitHub Actions workflow writing to a small hosted
  Postgres** (Neon/Supabase/RDS — researcher to pick). It must run independently of any laptop,
  because a gap in this history is permanent. The local compose Postgres remains for development.
- **D-13:** `symbol_listing_snapshot` stores the **raw compressed `exchangeInfo` payload plus
  extracted columns** (symbol, status, base/quote, tick size, step size, min notional,
  `captured_at`). The raw blob preserves fields not yet known to be needed — Binance adds filters
  over time, and an unextracted field is permanently lost for every past day.
  — **Reversibility:** one-way — a column not captured cannot be backfilled for historical days.
- **D-14:** One snapshot row is written **every day unconditionally**, even when byte-identical to
  the previous day. No dedup, no valid_from/valid_to ranges. A dedup'd table cannot distinguish
  "the universe did not change" from "the cron silently died", which is precisely what success
  criterion 4's gapless daily count exists to prove.
- **D-15:** `VALID-01` trials rows are written **on completion, plus a row for crashed or aborted
  runs**, so failed experiments are counted — PBO and deflated Sharpe in Phase 3 depend on an
  honest denominator.
  **KNOWN CEILING (deliberate):** a hard kill (SIGKILL, power loss) still loses the row. Upgrade
  path is write-ahead-then-update, which Phase 8 needs anyway for durable `clientOrderId`. Revisit
  if trial counts are ever observed to disagree with the run log.
- **D-16:** Credentials go through a **secrets manager from day one** (AWS Secrets Manager or
  equivalent), read by both the cron and local development. Establishing the pattern on a
  low-stakes database credential is cheaper than migrating to it under pressure in Phase 4 when
  real exchange keys arrive.

### The tool and the determinism contract

- **D-17:** The developer-facing tool is a **Python CLI in `engine/cli`**:
  `uv run backtest --symbol BTCUSDT --spec strategies/sma.json --from <date> --to <date> --out runs/`,
  also exposed through turbo as `pnpm backtest`. A single entry point is the natural choke point
  for the `VALID-01` trials write.
- **D-18:** The reproducibility contract is a **SHA-256 over canonically-serialised trades and
  equity curve** — sorted keys, decimal strings, fixed timestamp format, and no wall-clock,
  hostname, path or run-id anywhere in the hashed bytes. A test runs the same backtest twice and
  asserts hash equality. The plot is explicitly outside the contract.
  — **Reversibility:** costly — the canonical form becomes the reference Phase 2's acceptance gate
  reproduces against; changing it invalidates every recorded hash.
- **D-19:** A run writes a **minimal artifact set**: `trades.parquet`, `equity.parquet`,
  `hash.txt`. No manifest, no copied spec.
  **KNOWN CEILING (deliberate):** reproducing an old run means reconstructing which spec and which
  data version produced it. Phase 2's "reproduce a published backtest within tolerance" gate is
  where the full input manifest gets built properly.
- **D-20:** `--plot` renders a matplotlib PNG for eyeballing; it is gitignored and outside the hash.
  No web stack, no HTML report, no server in Phase 1 — the Phase 4 web app reads the same Parquet.

### Data ingestion and catalog

- **D-21:** Phase 1 ingests **BTCUSDT plus a handful of majors** — enough to surface bugs a single
  symbol hides (differing precision filters, symbols that delist mid-range), which is what the
  point-in-time universe work is about. The loader is written generally (symbol, interval, range
  are parameters); breadth arrives when Phase 3 needs it. Full survivorship-free universe is
  explicitly NOT Phase 1.
- **D-22:** **1-hour bars, full available history** per symbol from its listing date. Small enough
  that a handful of symbols is a quick ingest and cheap storage; long enough to span a full crypto
  cycle so a result means something. 1m is deferred — the loader is parameterised for it.
- **D-23:** The `ParquetDataCatalog` lives in **S3 from day one**, so both builders, CI, and the
  cron read the same bytes — serving success criterion 2's "two machines" directly.
  **Planner note:** this pulls AWS credentials and egress into Phase 1 and makes local iteration
  slower than a local disk read; consider a local read-through cache.
  — **Reversibility:** reversible — the catalog is a cache, re-derivable from Binance Vision.
- **D-24:** `DATA-06` — bars are **timestamped at close** (`ts_event` = bar close), asserted in
  tests. This is the convention that cannot look ahead.
  — **Reversibility:** one-way — every backtest result, every recorded hash, and every trials row
  produced under the other convention would be wrong by one bar.
- **D-25:** Checksum handling: a `CHECKSUM.txt` mismatch **hard-fails** that file and exits
  non-zero — silently accepting corrupt market data is how a backtest lies to you. Re-running
  ingestion **skips files already ingested and verified**, so it is idempotent and resumable.
- **D-26:** The first hand-written `StrategySpec` is a **simple SMA crossover** — two moving
  averages, cross to go long, cross back to flat. Deliberately minimal: it exercises indicator
  state, entry/exit, sizing and fills, and the resulting trade list can be verified by hand against
  the bars. **The DSL surface in Phase 1 is bounded to exactly what this spec needs** — the phase
  proves the seam, not the expressiveness.
  *(The user initially considered a strategy with real trading intent, then reverted to SMA
  crossover to keep Phase 1 minimal. Do not re-expand the DSL beyond the crossover.)*

### Claude's Discretion

- Choice of hosted Postgres provider (Neon / Supabase / RDS) for the cron target — researcher to
  weigh cost and setup friction.
- Exact set of "handful of majors" symbols beyond BTCUSDT.
- Codegen tool invocation details and where generated artifacts are gitignored to.
- Local read-through cache design for the S3 catalog, if the researcher finds iteration too slow.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Architecture and design intent
- `docs/Architecture_Plan.md` — original system architecture; note that several assumptions in it
  (hand-built OMS, hand-built fill/fee models) are superseded by the decision to use NautilusTrader.
- `docs/Quant-Phase.md` — platform design principles and build-order discipline; the source of the
  "backtest and live must share one code path" trust argument.
- `.planning/PROJECT.md` — **Key Decisions table is binding.** Contains the engine decision and its
  four revisit tripwires, the tenancy reversal with full defect evidence, the DSL seam definition,
  and the ledger-vs-execution-truth split.

### Requirements and scope
- `.planning/ROADMAP.md` §"Phase 1" — goal, the six success criteria, sizing (16–22 person-weeks),
  the two-workstream parallelism split, and the non-backfillable list.
- `.planning/REQUIREMENTS.md` — FOUND-01, FOUND-03, FOUND-04, FOUND-05, FOUND-06, FOUND-09,
  DATA-01, DATA-02, DATA-03, DATA-06, SIM-01, SIM-02, SIM-04, VALID-01 (14 requirements).

### Research
- `.planning/research/ARCHITECTURE.md`
- `.planning/research/STACK.md`
- `.planning/research/PITFALLS.md`
- `.planning/research/FEATURES.md`
- `.planning/research/SUMMARY.md`

### Upstream (after D-04 lands the submodule)
- `MIGRATION_V2.md` in the Nautilus checkout — **required reading.** v1-era tutorials and most
  model training data are wrong for v2; `TradingNode` does not exist, it is `LiveNode.builder(...)`.

### To be written in this phase
- `docs/adr/0001-shelve-tenancy-patch.md` — per D-05, does not exist yet.

</canonical_refs>

<code_context>
## Existing Code Insights

### Current state (scouted 2026-09-05)
The repository is an **unmodified Turborepo template**. There is no quant code of any kind and
`nautilus_trader` does not appear anywhere in the tree.

- `packages/fastapi-server` — literally `fastapi-blog`: users/posts routers, SQLAlchemy +
  aiosqlite, alembic, pwdlib/PyJWT auth. Python pinned to 3.13, managed by `uv`, ruff at
  line-length 120 with `E,F,I,UP,B,SIM,C4`.
- `apps/server` — Prisma (`postgresql` provider) with better-auth models (`user`, `session`,
  `account`), plus docker-compose, vitest. (The CDK stack and the Lambda entry point that were
  here have since been removed — the API is not going to Lambda.)
- `apps/web` — Next.js with shadcn-style `components.json`.
- Root `package.json` is still named `"template"`; pnpm 10.34.5, turbo 2.10.7, Node >= 18.
- `docs/Architecture_Plan.md` and `docs/Quant-Phase.md` are in-tree here.

### Reusable Assets
- **uv + ruff + pytest configuration** in `packages/fastapi-server/pyproject.toml` — copy the
  toolchain config into `engine/`; discard the blog dependencies.
- **Prisma setup** in `apps/server/prisma/` — becomes the standalone schema package per D-09 and
  gains the two Phase 1 tables. The better-auth models stay for Phase 4.
- **docker-compose files** (two exist: `apps/server/`, `packages/fastapi-server/`) — collapse into
  one root compose per D-10.
- **turbo task graph** (`build`, `dev`, `lint`, `check-types`, `test`) — the engine shim hooks
  straight into it per D-02/D-08.

### Established Patterns
- Python 3.13 + uv + ruff (line-length 120) is the existing Python convention — match it.
- pnpm workspace + turbo is the existing orchestration convention — the engine joins it via a
  `package.json` shim rather than replacing it.

### Integration Points
- `engine/` ↔ `schemas/strategy-spec.v1.json` via generated Pydantic models (D-06).
- `engine/` ↔ Postgres via SQLAlchemy Core against Prisma-migrated tables (D-11).
- `engine/adapters/dsl_strategy.py` ↔ the Nautilus submodule — **the only Nautilus import site in
  the whole engine** (`FOUND-06`); success criterion 3 enforces this with
  `grep -rl nautilus_trader engine/dsl/` returning nothing.
- GitHub Actions ↔ hosted Postgres for the daily snapshot (D-12).

</code_context>

<specifics>
## Specific Ideas

- Success criterion 3 is a literal grep — `grep -rl nautilus_trader engine/dsl/` must return
  nothing, and the `DslEvaluator` suite must run against a plain list of bars in under a second
  with no engine present. Build the grep into CI, not into a checklist.
- Success criterion 4 is a literal query — `SELECT count(*) FROM symbol_listing_snapshot` grows by
  one per day with no gaps. D-14's no-dedup rule exists to keep that query meaningful.
- The roadmap names two clean workstreams from day one: **(A)** data ingestion and the PIT universe,
  **(B)** contracts, `DslEvaluator`, and the `DslStrategy` adapter. They meet at the first backtest.
  Plan the waves along that seam.
- Two out-of-band items belong in this phase: measure the Rust rebuild time in week one (PROJECT.md
  tripwire 3 — D-04's submodule choice is what makes this measurable), and archive the tenancy
  branch (D-05).

</specifics>

<deferred>
## Deferred Ideas

- **Full survivorship-free symbol universe** — the roadmap flags it as the hard part of ingestion.
  Phase 1 takes a handful of majors (D-21); the full universe belongs where validation needs it.
- **1-minute bar ingestion** — loader is parameterised for it (D-22); ingest when live execution
  resolution actually matters.
- **Full run input manifest** (input data hash, spec hash, engine SHA, lockfile hash) — Phase 2's
  "reproduce a published backtest within tolerance" acceptance gate.
- **Write-ahead trials rows** — upgrade path for D-15's known ceiling; Phase 8 builds the same
  write-ahead discipline for durable `clientOrderId`.
- **A second, structurally different StrategySpec** to prove the DSL is a language rather than one
  hardcoded strategy — considered and dropped from Phase 1 to keep the DSL surface bounded.
- **A strategy with real trading intent** — user raised it, then reverted to SMA crossover to keep
  Phase 1 minimal. Belongs after the seam is proven and the DSL has grown deliberately.
- **HTML / interactive backtest report** — Phase 4's web app, reading the same Parquet.
- **LiveNode supervisor API** on the retained FastAPI shell (D-03) — Phase 5.
- **TS and SQL float-in-money guards** made real (D-07) — Phase 4, when those languages first
  handle money.

</deferred>

---

*Phase: 1-walking-skeleton-backtest-a-hand-written-spec-on-real-data*
*Context gathered: 2026-09-05*
