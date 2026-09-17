# Phase 1: Walking Skeleton — Backtest a Hand-Written Spec on Real Data - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-05
**Phase:** 1-walking-skeleton-backtest-a-hand-written-spec-on-real-data
**Areas discussed:** Repo structure + engine layout, trials + snapshot storage, The tool + what determinism asserts, Ingestion scope + catalog

*Note: the user added "Modification of Project Repo structure to fit our needs" as a fifth area; it was merged into "Repo structure + engine layout" as the same decision surface.*

---

## Repo structure + engine layout

### Scaffold fate

| Option | Description | Selected |
|--------|-------------|----------|
| Strip demo, keep shells | Delete demo domain code; keep empty app shells, tooling, better-auth models | |
| Freeze TS, add Python | Touch nothing; add engine alongside until Phase 4 | |
| Full restructure now | Rename template, retire fastapi-server's blog stack, reshape to the architecture's layout | ✓ |

**User's choice:** Full restructure now
**Notes:** Accepts higher up-front cost so the tree matches the architecture from commit one rather than being renamed under load later.

### Top-level layout

| Option | Description | Selected |
|--------|-------------|----------|
| Top-level engine/, keep turbo | Python uv project at `engine/`; turbo root retained via package.json shim; `schemas/` at root | ✓ |
| Split by plane, not language | `spine/` `control-plane/` `ai/` — organised by architecture boundary; breaks criterion 3's literal `engine/dsl/` grep | |
| Two repos, split now | Engine in its own repo; FOUND-04 schema must cross a repo boundary from day one | |

**User's choice:** Top-level engine/, keep turbo
**Notes:** Chosen from a rendered tree preview. Matches success criterion 3's literal grep path.

### packages/fastapi-server

| Option | Description | Selected |
|--------|-------------|----------|
| Delete it | TS owns the control plane; a second Python HTTP server duplicates auth surface | |
| Keep as engine control API | Strip the blog; retain FastAPI shell as the Phase 5 per-tenant LiveNode supervisor surface | ✓ |
| Delete, revisit at Phase 5 | Remove now; make the supervisor shape an explicit Phase 5 question | |

**User's choice:** Keep as engine control API

### FOUND-09 — which three languages

| Option | Description | Selected |
|--------|-------------|----------|
| Python, TS, SQL | Guard the three places money is represented; Rust is stock upstream, not ours | ✓ |
| Python, TS, Rust | Also assert upstream Nautilus types are Decimal-backed; tests code we don't own | |
| Python only in Phase 1 | Defer TS and SQL guards to Phase 4 | |

**User's choice:** Python, TS, SQL
**Notes:** Only the Python guard is buildable in Phase 1; TS and SQL land as stubs.

### FOUND-04 — how Python and TS consume StrategySpec

| Option | Description | Selected |
|--------|-------------|----------|
| Schema is source, codegen both | Hand-written JSON Schema authoritative; generate Pydantic + TS at build time | ✓ |
| Pydantic is source, emit schema | Better Phase 1 ergonomics; Python becomes de facto authoritative | |
| Schema is source, validate only | No codegen; shared conformance fixtures catch drift instead of preventing it | |

**User's choice:** Schema is source, codegen both
**Notes:** Neither language authoritative, so neither can drift. Costs a codegen step in turbo.

### Nautilus consumption

| Option | Description | Selected |
|--------|-------------|----------|
| Wheel pin + source clone | Hash-locked wheel for dev speed; separate one-off clone for the tripwire measurement | |
| Git dependency at commit | uv installs from git at an exact SHA; Rust rebuilt continuously; slow CI and onboarding | |
| Submodule + editable install | Source always in-tree and readable; every dev needs a Rust toolchain | ✓ |

**User's choice:** Submodule + editable install
**Notes:** Raised tension — PROJECT.md tripwire 3 requires measuring Rust rebuild time, which a published wheel never exercises. Submodule resolves it and keeps the cited upstream source paths readable.

### FOUND-03 — tenancy archive record

| Option | Description | Selected |
|--------|-------------|----------|
| docs/ ADR + tagged branch | Dated ADR with defect evidence; branch preserved as an archive tag on our fork | ✓ |
| ADR only, no branch | SHA `768cbf3664` recoverable from upstream history | |
| Record inside PROJECT.md | Expand the existing Key Decisions row rather than start an ADR directory | |

**User's choice:** docs/ ADR + tagged branch

### CI shape

| Option | Description | Selected |
|--------|-------------|----------|
| One turbo pipeline | Single entry point; engine shim delegates to uv; needs Node+pnpm+Python+Rust in the image | ✓ |
| Split jobs by language | Independent Python and TS jobs; heavy Rust build isolated; two pipelines to sync | |
| Python-only CI for now | Engine tests plus the FOUND-06 grep and FOUND-09 guard; dormant apps can rot | |

**User's choice:** One turbo pipeline

### Dormant TS apps

| Option | Description | Selected |
|--------|-------------|----------|
| Keep green, minimal surface | Both stay in the workspace, stripped to shells, must build | |
| Prisma live, apps parked | Prisma extracted as a real Phase 1 dependency; apps/web + apps/server out of the workspace until Phase 4 | ✓ |
| Keep everything as-is | Zero work now; a 12-month-stale Next.js upgraded under pressure later | |

**User's choice:** Prisma live, apps parked

### Local dev / Docker

| Option | Description | Selected |
|--------|-------------|----------|
| One compose at root | Single compose for Postgres, replacing the template's two; engine runs on the host | |
| Compose + devcontainer | Root compose plus a devcontainer pinning Python, Node, pnpm and Rust | ✓ |
| Postgres only, no compose | Locally installed Postgres; smallest setup; environments can drift | |

**User's choice:** Compose + devcontainer
**Notes:** Makes success criterion 2 ("byte-identical on two machines") an environment guarantee.

---

## trials + snapshot storage

### Where Phase 1 data lands

| Option | Description | Selected |
|--------|-------------|----------|
| Postgres now, Python owns | Python owns the two tables via its own alembic; two schema owners in one DB | |
| Postgres now, Prisma owns | Prisma is sole schema owner; Python writes via SQLAlchemy Core into Prisma-migrated tables | ✓ |
| Local files now, load later | Parquet/SQLite in Phase 1; zero infra; a real load task lands in Phase 4 | |

**User's choice:** Postgres now, Prisma owns
**Notes:** Consequence surfaced during discussion — an otherwise pure-Python phase now depends on the TS toolchain to run a migration.

### DATA-03 cron host

| Option | Description | Selected |
|--------|-------------|----------|
| GH Actions → hosted Postgres | Runs regardless of any laptop; a hosted DB and credentials exist from Phase 1 | ✓ |
| GH Actions → commit to repo | Zero infra, git-versioned history; criterion 4's SQL count unsatisfiable until loaded | |
| EventBridge + Lambda | Uses the existing CDK; stands up AWS/VPC/RDS in week one | |

> Since this discussion, the CDK stack and the Lambda entry point have been removed from
> `apps/server` — the API is not being deployed to Lambda. The rejected option above is left as
> written because it records what was weighed at the time; its "existing CDK" premise no longer
> holds, which only strengthens the choice that was made.

**User's choice:** GH Actions → hosted Postgres
**Notes:** Tension raised — a compose-only Postgres cannot be written to by anything off the laptop, which defeats a non-backfillable daily history.

### Criterion 5 — every run writes a trial

| Option | Description | Selected |
|--------|-------------|----------|
| Write in the runner, no opt-out | Row written before anything computes; no alternate path into the engine | |
| Write on completion + failures | Row on finish, plus a row for crashed/aborted runs; a hard kill still loses it | ✓ |
| Write-ahead then update | Insert before, update after; crashes leave a visible incomplete row | |

**User's choice:** Write on completion + failures
**Notes:** Known ceiling accepted and recorded in CONTEXT.md as D-15 — hard kill loses the row; upgrade path is write-ahead, which Phase 8 needs anyway.

### Snapshot row contents

| Option | Description | Selected |
|--------|-------------|----------|
| Raw blob + extracted columns | Compressed payload plus queryable columns; unknown-future fields survive | ✓ |
| Extracted columns only | Small and clean; an unextracted field is permanently lost for every past day | |
| Raw blob only, parse on read | Nothing lost, no schema risk; every query parses JSON and Prisma models blobs poorly | |

**User's choice:** Raw blob + extracted columns

### Dedup

| Option | Description | Selected |
|--------|-------------|----------|
| Store every day, always | Unconditional daily row; keeps criterion 4's gapless count meaningful | ✓ |
| Store every day, hash for change | Same, plus a payload_hash for cheap change detection | |
| Dedup, store on change only | Smallest table, cleanest PIT semantics; breaks criterion 4 as written | |

**User's choice:** Store every day, always
**Notes:** A dedup'd table cannot distinguish "unchanged" from "the cron died".

### Credentials

| Option | Description | Selected |
|--------|-------------|----------|
| GH Secrets + local .env | Simplest thing that holds; real vault treatment arrives with Phase 4 exchange keys | |
| Secrets manager from day one | Pattern is right from the first secret rather than migrated under pressure later | ✓ |
| Separate write-only cron role | GH Secrets plus least-privilege INSERT-only Postgres role for the cron | |

**User's choice:** Secrets manager from day one

---

## The tool + what determinism asserts

### The tool

| Option | Description | Selected |
|--------|-------------|----------|
| Python CLI in engine/cli | One scriptable entry point; natural choke point for the trials write | ✓ |
| CLI + notebook companion | Matches how quant work is done; a second invocation path to police | |
| Library-first, thin CLI | `run_backtest()` primary; easiest to call from Phase 3 and Phase 10 | |

**User's choice:** Python CLI in engine/cli

### What byte-identical covers

| Option | Description | Selected |
|--------|-------------|----------|
| Hashed canonical artifacts | Canonical trades + equity, SHA-256'd; plot explicitly outside the contract | ✓ |
| Full run manifest | Also hashes input data, spec, engine SHA, lockfile — tells you which input drifted | |
| Hash outputs, assert in CI | Canonical hashes plus a committed golden fixture CI asserts against | |

**User's choice:** Hashed canonical artifacts

### Run artifacts

| Option | Description | Selected |
|--------|-------------|----------|
| Dir per run, canonical set | spec, trades, equity, result, manifest, hash — everything hashed is diffable | |
| Minimal: trades + equity + hash | Smallest thing satisfying criteria 1 and 2 | ✓ |
| Content-addressed runs | Directory named by input hash; determinism visible in the filesystem | |

**User's choice:** Minimal: trades + equity + hash
**Notes:** Known ceiling recorded as D-19 — reproducing an old run needs spec and data version reconstructed; Phase 2's acceptance gate builds the full manifest.

### Looking at the curve

| Option | Description | Selected |
|--------|-------------|----------|
| Parquet + --plot PNG | Data is the deliverable; matplotlib PNG for eyeballing, outside the hash | ✓ |
| Parquet only, plot elsewhere | Zero plotting dependency in engine/ | |
| Self-contained HTML report | Interactive chart and trade table inline; a charting dependency to maintain | |

**User's choice:** Parquet + --plot PNG

---

## Ingestion scope + catalog

### Scope

| Option | Description | Selected |
|--------|-------------|----------|
| One symbol, one interval | Thinnest thing that exercises the spine | |
| Few symbols, one interval | Catches bugs a single symbol hides — precision filters, mid-range delistings | ✓ |
| Full survivorship-free universe | Kills survivorship bias at the source; largest cost by far | |

**User's choice:** Few symbols, one interval

### Catalog location and timestamp convention

| Option | Description | Selected |
|--------|-------------|----------|
| Local gitignored + close-stamped | Catalog as a re-derivable cache; no cloud until something else must read it | |
| S3 from day one | Both builders, CI and cron read the same bytes; serves criterion 2 directly | ✓ |
| Local + open-stamped | Straight copy of Binance Vision's raw layout; look-ahead one forgotten offset away | |

**User's choice:** S3 from day one (close-stamped bars)

### Interval and history depth

| Option | Description | Selected |
|--------|-------------|----------|
| 1h, full available history | Cheap for a handful of symbols; spans a full crypto cycle | ✓ |
| 1m, 2-3 years | The resolution live trading cares about; far larger ingest | |
| 1d + 1h, full history | Exercises multi-resolution layout from the start; two ingest paths to verify | |

**User's choice:** 1h, full available history

### Checksums

| Option | Description | Selected |
|--------|-------------|----------|
| Hard fail + idempotent skip | Abort on mismatch, exit non-zero; re-runs skip already-verified files | ✓ |
| Hard fail + always re-verify | Also re-verifies existing files; catches post-hoc S3 or disk corruption | |
| Retry then fail | Re-download once for transient truncation; masks a genuinely bad upstream file | |

**User's choice:** Hard fail + idempotent skip

### First StrategySpec

| Option | Description | Selected |
|--------|-------------|----------|
| SMA crossover | Canonical walking-skeleton strategy; trade list verifiable by hand | ✓ |
| SMA crossover + a second spec | Proves the DSL is a language, not one strategy in JSON | |
| Something with real intent | Phase 1 output is informative rather than a smoke test | |

**User's choice:** SMA crossover
**Notes:** Initially chose "something with real intent". Claude flagged that a real strategy pulls indicator, sizing and rule semantics into a phase already sized at 16–22 person-weeks with ingestion as the long pole, and asked for the concrete strategy so the DSL surface could be bounded. User reverted: *"actually just do SMA crossover, keep it minimal."* The DSL surface in Phase 1 is bounded to exactly what the crossover needs.

---

## Claude's Discretion

- Hosted Postgres provider (Neon / Supabase / RDS) for the cron target
- Exact set of majors beyond BTCUSDT
- Codegen invocation details and gitignore targets for generated types
- Local read-through cache for the S3 catalog, if iteration proves too slow

## Deferred Ideas

- Full survivorship-free symbol universe (Phase 3, where validation needs it)
- 1-minute bar ingestion (loader already parameterised)
- Full run input manifest (Phase 2 acceptance gate)
- Write-ahead trials rows (Phase 8 builds the same discipline for clientOrderId)
- A second, structurally different StrategySpec
- A strategy with real trading intent — raised, then reverted to keep Phase 1 minimal
- HTML / interactive backtest report (Phase 4 web app)
- LiveNode supervisor API on the retained FastAPI shell (Phase 5)
- TS and SQL float-in-money guards made real (Phase 4)
