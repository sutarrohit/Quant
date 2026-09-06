# Phase 1: Walking Skeleton — Research

**Researched:** 2026-09-06
**Domain:** NautilusTrader v2 backtest engine (editable git-submodule install), Binance Vision bulk
data ingestion, byte-identical determinism, a pure-Python DSL evaluator seam, Prisma-owned/Python-
written Postgres tables, and JSON-Schema-as-source-of-truth codegen.
**Confidence:** HIGH on the Nautilus v2 API surface and the Binance Vision data format (both
verified directly against the pinned submodule checkout and live `data.binance.vision` fetches this
session). MEDIUM on Prisma/codegen integration patterns (verified against official docs, not this
repo's actual migrations, which do not exist yet). LOW/flagged-for-spike on one item: mapping a
JSON-Schema decimal-string field to a strict Python `Decimal` type via `datamodel-code-generator`
has no documented out-of-the-box flag — see Open Questions.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Full restructure of the Turborepo template now, rather than adding alongside it.
- **D-02:** Top-level `engine/` as a uv project on Python 3.13, containing `dsl/` (pure —
  `spec.py`, `evaluator.py`), `adapters/dsl_strategy.py` (the sole file importing both
  `DslEvaluator` and Nautilus), `data/`, `cli/`, `tests/`. Shared JSON Schema lives in top-level
  `schemas/`.
- **D-03:** `packages/fastapi-server` is kept but stripped of the `fastapi-blog` template domain;
  reserved for Phase 5's `LiveNode` supervisor. No role in Phase 1.
- **D-04:** NautilusTrader v2 is consumed as a **git submodule pinned to an exact commit, installed
  editable** — not a published wheel. Every developer/CI job needs a Rust toolchain; cold builds are
  slow. Pin the commit, not the `v2.0.0rc4` tag.
- **D-05:** `FOUND-03` archive record is `docs/adr/0001-shelve-tenancy-patch.md`; branch preserved as
  `archive/tenancy-768cbf3664` tag.
- **D-06:** `schemas/strategy-spec.v1.json` is the source of truth. Pydantic via
  `datamodel-code-generator`, TS via `json-schema-to-typescript`, both into gitignored directories at
  build time. Neither language is authoritative.
- **D-07:** `FOUND-09` float-in-money guard covers Python, TypeScript, and SQL. Only Python must be
  real in Phase 1; TS/SQL land as stubs, real in Phase 4.
- **D-08:** CI is one turbo pipeline — `turbo run test lint check-types` — engine shim delegates to
  uv. CI image needs Node, pnpm, Python 3.13, and a Rust toolchain.
- **D-09:** Prisma is extracted into its own workspace package. `apps/web` and `apps/server` are
  removed from the workspace until Phase 4.
- **D-10:** A single root `docker-compose.yml` owns Postgres. A devcontainer pins Python 3.13, Node,
  pnpm, and the Rust toolchain.
- **D-11:** Postgres exists from Phase 1, **Prisma as the sole schema owner**. `trials` and
  `symbol_listing_snapshot` are declared in `schema.prisma`; Python writes via SQLAlchemy Core.
- **D-12:** The `DATA-03` cron is a scheduled GitHub Actions workflow writing to a small hosted
  Postgres (Neon/Supabase/RDS). Local compose Postgres remains for development.
- **D-13:** `symbol_listing_snapshot` stores the raw compressed `exchangeInfo` payload plus extracted
  columns (symbol, status, base/quote, tick size, step size, min notional, `captured_at`).
- **D-14:** One snapshot row written every day unconditionally, even when byte-identical to the
  previous day. No dedup.
- **D-15:** `VALID-01` trials rows written on completion, plus a row for crashed/aborted runs. Known
  ceiling: a hard kill still loses the row (write-ahead is Phase 8's upgrade path).
- **D-16:** Credentials go through a secrets manager from day one (AWS Secrets Manager or
  equivalent).
- **D-17:** The developer-facing tool is a Python CLI in `engine/cli`:
  `uv run backtest --symbol BTCUSDT --spec strategies/sma.json --from <date> --to <date> --out
  runs/`, also exposed as `pnpm backtest`.
- **D-18:** The reproducibility contract is a SHA-256 over canonically-serialised trades and equity
  curve — sorted keys, decimal strings, fixed timestamp format, no wall-clock/hostname/path/run-id.
  The plot is outside the contract.
- **D-19:** A run writes a minimal artifact set: `trades.parquet`, `equity.parquet`, `hash.txt`. No
  manifest, no copied spec (known ceiling — full manifest is Phase 2's job).
- **D-20:** `--plot` renders a gitignored matplotlib PNG, outside the hash. No web stack in Phase 1.
- **D-21:** Phase 1 ingests BTCUSDT plus a handful of majors. Loader is general (symbol, interval,
  range are parameters). Full survivorship-free universe is explicitly NOT Phase 1.
- **D-22:** 1-hour bars, full available history per symbol from its listing date. 1m is deferred.
- **D-23:** The `ParquetDataCatalog` lives in S3 from day one.
- **D-24:** `DATA-06` — bars are timestamped at close (`ts_event` = bar close), asserted in tests.
- **D-25:** A `CHECKSUM.txt` mismatch hard-fails that file and exits non-zero. Re-running ingestion
  skips files already ingested and verified.
- **D-26:** The first hand-written `StrategySpec` is a simple SMA crossover. The DSL surface in
  Phase 1 is bounded to exactly what this spec needs — do not re-expand it.

### Claude's Discretion

- Choice of hosted Postgres provider (Neon / Supabase / RDS) for the cron target.
- Exact set of "handful of majors" symbols beyond BTCUSDT.
- Codegen tool invocation details and where generated artifacts are gitignored to.
- Local read-through cache design for the S3 catalog, if iteration proves too slow.

### Deferred Ideas (OUT OF SCOPE)

- Full survivorship-free symbol universe (Phase 2/3).
- 1-minute bar ingestion (loader is parameterised for it; ingest when live execution needs it).
- Full run input manifest (input data hash, spec hash, engine SHA, lockfile hash) — Phase 2's
  `SIM-05` gate.
- Write-ahead trials rows — Phase 8.
- A second, structurally different `StrategySpec` — dropped to keep the DSL surface bounded.
- A strategy with real trading intent — reverted to SMA crossover to keep Phase 1 minimal.
- HTML / interactive backtest report — Phase 4's web app.
- `LiveNode` supervisor API on the retained FastAPI shell — Phase 5.
- TS and SQL float-in-money guards made real — Phase 4.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FOUND-01 | Stock NautilusTrader v2 `LiveNode` runs from a pinned upstream commit, no local patches | Confirmed pinned commit `be9eaff8a7` matches `version.json`'s `v2.0.0rc4` and is not stale against PyPI's own rc4; D-04's editable-submodule install path, toolchain requirements, and cold-build-time risk are documented in Standard Stack and Pitfall 4. Phase 1 only needs the backtest engine, not `LiveNode` itself (that's Phase 5) — the requirement is satisfied by the submodule/commit-pin mechanics being correct now. |
| FOUND-03 | Tenancy branch archived with a written record | Out of this research's technical scope (a documentation task, D-05) — no engine-API research needed; `docs/adr/0001-shelve-tenancy-patch.md` content already exists in PROJECT.md's Key Decisions table per CONTEXT.md. |
| FOUND-04 | `StrategySpec` versioned JSON schema, single source of truth for all three languages | Architecture Pattern 4 and Pitfall 3 cover the JSON-Schema-as-source-of-truth codegen pipeline (`datamodel-code-generator` → Pydantic, `json-schema-to-typescript` → TS) and the specific gap (string-typed decimal fields) that needs a spike. |
| FOUND-05 | `DslEvaluator` pure Python, zero Nautilus imports, testable against a list of bars | Architecture Pattern 2 shows the exact `Strategy`/`DslEvaluator` split; Validation Architecture's Wave 0 gaps include the Nautilus-free CI job needed to prove this. |
| FOUND-06 | `DslStrategy` is the only file importing both `DslEvaluator` and Nautilus | Architecture Pattern 2 and Don't Hand-Roll (purity boundary enforcement via the literal grep) directly address this. |
| FOUND-09 | All monetary values are decimal strings; a test fails the build on a float reaching a money field | Summary's second finding, Pitfall 2 (`Position.signed_qty` float leak), and the Code Examples money-guard test (Pydantic `strict=True` Decimal) together give a concrete, verified mechanism for the Python half required this phase. |
| DATA-01 | Binance spot OHLCV ingested from `data.binance.vision` with checksum verification | Research priority 2 — URL layout, CHECKSUM format (verified byte-for-byte this session), and CSV schema are fully documented in Summary, Pitfall 1, and Security Domain. |
| DATA-02 | Ingested data stored in a `ParquetDataCatalog` the engine reads natively | Architecture Pattern 1 and Pattern 3 cover `ParquetDataCatalog.write_bars`/`write_instruments` and catalog-driven `BacktestNode` reads. |
| DATA-03 | Daily `exchangeInfo` snapshot builds point-in-time symbol history | `exchangeInfo` REST shape verified against the real fixture JSON (Summary, Architecture diagram); Validation Architecture flags this criterion's inherently time-based nature (cannot be satisfied same-day as the code). |
| DATA-06 | Bar timestamp semantics (open vs close) explicit in the catalog, asserted in tests | Pattern 3's code example sets `ts_event = close_time_ns` explicitly; Pitfall 1's timestamp-unit finding is a prerequisite for getting this right at all. |
| SIM-01 | Backtest a strategy version over a date range, see an equity curve | Architecture Pattern 1 (`BacktestNode`) and Don't Hand-Roll (`generate_account_report()` as the equity-curve source) directly support this. |
| SIM-02 | Backtests deterministic and replayable — identical input, identical output | Research priority 3 (Summary, Anti-Patterns, Code Examples determinism test) is the core of this requirement's research. |
| SIM-04 | Same `DslEvaluator` code path runs in backtest, paper, and live; only adapters differ | Architecture Pattern 2's strict `DslStrategy`/`DslEvaluator` split is what makes this structurally true; Phase 1 only proves the backtest leg. |
| VALID-01 | Every optimization run recorded in `trials` from the very first backtest | Architecture Pattern 4 (Prisma/SQLAlchemy Core writer, the `dbgenerated` UUID fix) and Validation Architecture's test map directly address the write-on-crash requirement (D-15). |
</phase_requirements>

## Summary

The engine-facing half of this phase (`BacktestEngine`/`BacktestNode`, `Strategy.on_start`/`on_bar`,
`ParquetDataCatalog`) has real, working, catalog-driven examples in the pinned Nautilus v2 checkout
at `/Users/criox4/Codes/Trade_Platform/Nautilus_Engine /nautilus_trader` (commit `be9eaff8a7`,
`v2.0.0rc4`) — `docs/getting_started/backtest_high_level.py` is close to a template for the Phase 1
CLI, and `docs/getting_started/backtest_low_level.py` backtests an EMA cross **on a simulated
Binance Spot venue** with the exact `Strategy` lifecycle Phase 1 needs. Binance Spot is a supported,
non-experimental adapter product (`docs/integrations/binance.md`: "Spot Markets (incl. Binance US) —
✓"), and `load_binance_instruments()` fetches real `exchangeInfo`-derived `CurrencyPair` instruments
without credentials in JSON mode.

The single most consequential finding this session is **not in any doc**: live-fetching real
`data.binance.vision` files proved that Binance Vision klines silently changed timestamp units from
milliseconds to **microseconds** starting with data dated 2025-01-01 onward (same 12-column,
no-header CSV shape, same URL layout — only the digit count changes). A loader that assumes one
fixed timestamp unit will silently misinterpret every bar from a boundary-crossing ingest and violate
`DATA-06` without ever throwing an exception. This must be handled by inspecting digit count (13 vs
16) per file, not by a global constant.

The second load-bearing finding is that Nautilus's own `.to_dict()` methods on `OrderFilled`,
`AccountBalance`, and `MarginBalance` already emit decimal **strings**, not floats — `FOUND-09`'s
Python guard is mostly free if the CLI persists these dicts as-is. The one exception Nautilus's own
authors found and patched around: `Position.to_dict()["signed_qty"]` is a raw float, and
`ReportProvider.generate_positions_report` explicitly deletes that column before returning the
report — the Phase 1 persistence code must do the same for anything it pulls from `Position` objects
directly.

The third: the `trials`/`symbol_listing_snapshot` tables using Prisma's `@default(uuid())` (the
current pattern in `apps/server/prisma/schema.prisma`) generates the ID in the Prisma **client**, not
in Postgres — a bare SQLAlchemy Core `INSERT` without that ID present will violate the `NOT NULL`
primary-key constraint. The two Phase 1 tables need either `@default(dbgenerated("gen_random_uuid()"))
@db.Uuid` or a plain autoincrementing integer key, not the current pattern's `uuid()`/`cuid()`.

**Primary recommendation:** Build the CLI on `BacktestNode` + `BacktestDataConfig` reading a
catalog-backed `ParquetDataCatalog`, construct `Bar` objects directly from parsed Binance Vision CSV
rows using `Price.from_str`/`Quantity.from_str` (never `float()`), leave `FillModel` and `FeeModel`
at Nautilus defaults (`FillModel()` and `MakerTakerFeeModel()`) so the backtest has zero configured
randomness sources, and compute the reproducibility hash over a canonical re-serialization of
`generate_account_report()` + `generate_positions_report()` output — never over raw Parquet bytes,
whose footer embeds a `parquet-cpp-arrow` version string.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Binance Vision ingestion, checksum verify | Python `engine/data` | — | Pure ETL, no engine involvement; runs standalone or via CLI subcommand |
| `ParquetDataCatalog` (S3-backed) | Python `engine/data` (write) | Nautilus `BacktestEngine`/`BacktestNode` (read) | Catalog is the seam between ingestion and backtest — both sides only ever touch Parquet |
| `DslEvaluator` (pure logic: SMA cross → entry/exit signal) | Python `engine/dsl/` | — | Zero Nautilus imports — `FOUND-05`/`FOUND-06` require this to be a plain-bars-in, signal-out function |
| `DslStrategy` (Nautilus `Strategy` subclass) | Python `engine/adapters/` (Nautilus embedding) | — | The **only** file that imports both `DslEvaluator` and `nautilus_trader` — the grep-enforced lock-in surface |
| Backtest execution, fills, positions, account state | NautilusTrader v2 (`BacktestEngine`) | — | Execution truth; Phase 1 does not reimplement any of this |
| Equity curve / trade list extraction | Python `engine/cli` (post-run) | Nautilus `analysis.ReportProvider` (data source) | CLI calls Nautilus's own report generators, then canonicalizes and hashes the result |
| `trials` / `symbol_listing_snapshot` schema | Prisma (`prisma/schema.prisma`) | Python `engine/data` (writer, via SQLAlchemy Core) | D-11: one schema owner; Python never runs a migration |
| `exchangeInfo` daily cron | GitHub Actions (scheduled workflow) | Hosted Postgres (target) | D-12: must run independent of any developer machine |
| `StrategySpec` contract | `schemas/strategy-spec.v1.json` (source of truth) | Generated Pydantic (Python) / generated TS (unused until Phase 4) | D-06: neither language is authoritative |
| Money-as-Decimal enforcement | Python (`Decimal`, Pydantic `strict=True`) | — (TS/SQL are stubs this phase, D-07) | Only the Python guard needs to be real in Phase 1 |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `nautilus_trader` | `2.0.0rc4` @ pinned commit `be9eaff8a7` (submodule, editable) | Backtest engine, execution truth, `ParquetDataCatalog` | Locked by D-04/PROJECT.md. `[VERIFIED: /Users/criox4/Codes/Trade_Platform/Nautilus_Engine /nautilus_trader/version.json — "message": "v2.0.0rc4"; git log -1 → be9eaff8a7f50ec72dd54cd0cd894fdc127e69bf 2026-09-02]`. PyPI's latest is also `2.0.0rc4` as of this session `[VERIFIED: pypi.org/pypi/nautilus_trader/json — releases include 2.0.0rc1..rc4, no newer]`, confirming the pinned commit is not stale against upstream's own release cadence. |
| Python | `3.13` | Engine + DSL runtime | `[VERIFIED: /Users/criox4/Codes/Trade_Platform/Nautilus_Engine /nautilus_trader/python/pyproject.toml:25 — requires-python = ">=3.12,<3.15"]`. 3.13 is inside this range and matches the existing `packages/fastapi-server` pin. |
| `maturin` | `==1.15.0` (exact) | Builds the Rust extension for editable install | `[VERIFIED: .../python/pyproject.toml:43 — requires = ["maturin==1.15.0", "patchelf"]]`. PyPI confirms `1.15.0` is current `[VERIFIED: pypi.org/pypi/maturin/json]`. |
| `uv` | `>=0.12,<0.13` | Python packaging for both `engine/` and the Nautilus submodule | `[VERIFIED: .../python/pyproject.toml:67 — required-version = ">=0.12,<0.13"]`. The local dev machine already has `uv 0.12.0` installed `[VERIFIED: uv --version, this session]` — no action needed for that machine, but the devcontainer (D-10) must pin the same range. |
| Rust toolchain | `>=1.98.0` (floor) | Compiles the Nautilus Rust core | `[VERIFIED: .../Cargo.toml:54 — rust-version = "1.98.0"]`. This is a Cargo `rust-version` floor, not necessarily what upstream CI uses — confirm the CI-pinned toolchain file (`rust-toolchain.toml`, if present) before building the devcontainer image. |
| `pydantic` | `2.13.5` | Generated `StrategySpec` models, Decimal validation | `[CITED: STACK.md prior research, PyPI JSON API]` — not re-verified this session, unchanged since. |
| `datamodel-code-generator` | `0.76.2` | JSON Schema → Pydantic v2 models (build-time, gitignored output) | `[VERIFIED: pypi.org/pypi/datamodel-code-generator/json — "version": "0.76.2"]`, live query this session. |
| `json-schema-to-typescript` | `16.0.0` | JSON Schema → TS types (build-time, gitignored output; unused by any running code until Phase 4, but exercised in CI per D-06) | `[VERIFIED: npm view json-schema-to-typescript version, this session]` |
| `polars` | `1.44.1` | Binance Vision CSV parsing at ingestion scale | `[CITED: STACK.md prior research]`. Not strictly required for 1h bars at "a handful of majors" (row counts are small — see Common Pitfalls); `csv` stdlib + direct `Bar()` construction (Nautilus's own pattern, see Code Examples) may be simpler and is the ponytail-lazy choice for Phase 1's actual data volume. |
| `SQLAlchemy` (Core only, not ORM) | `2.x` | Python writer into Prisma-migrated `trials`/`symbol_listing_snapshot` | D-11. Core, not the ORM, because there is no Python-side model authority — see Architecture Patterns. |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pyarrow` | `25.0.1` (per prior STACK.md research) | Only if reading the catalog outside Nautilus, or writing Parquet directly for `trades.parquet`/`equity.parquet` artifacts | D-19's minimal artifact set — `ParquetDataCatalog` itself may be sufficient; a plain `pyarrow.parquet.write_table` call is enough for the run-output artifacts and avoids adding a catalog dependency to the CLI's output path. |
| `import-linter` | `2.15` | Optional CI enforcement of the `engine/dsl/` purity boundary | `[VERIFIED: pypi.org/pypi/import-linter/json]`. **Not recommended over the literal grep** — success criterion 3 is itself `grep -rl nautilus_trader engine/dsl/`, so a grep-based CI step is simplest and directly matches the acceptance test. Only reach for `import-linter` if the boundary later needs finer-grained "no X imports Y" rules beyond this one seam (ponytail: don't add a dependency the acceptance criterion doesn't need). |
| `boto3` or `fsspec`+`s3fs` | latest | S3-backed `ParquetDataCatalog` (D-23) | `ParquetDataCatalog(base_path, storage_options=...)` accepts `storage_options` for S3 credentials — confirm the exact fsspec/object-store backend Nautilus's Rust core uses (`storage_options` mapping is generic; verify at implementation time whether it wants `fsspec`-style keys or AWS SDK env vars). |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Direct `Bar()` construction from parsed CSV rows | `BarDataWrangler.process_record_batch_bytes()` (Arrow IPC bytes) | The wrangler path is what high-throughput tick ingestion uses internally, but it requires building an Arrow `RecordBatch` with a specific schema first — more moving parts for the same result at 1h-bar row counts (~8,760 rows/symbol/year). Nautilus's own `TestDataProvider.bars_from_binance_csv` test helper constructs `Bar` objects directly in a loop — that is the simpler, equally-correct pattern for Phase 1's data volume. |
| `MakerTakerFeeModel()` (uses the instrument's real fee rates) | `FixedFeeModel(commission=...)` | `FixedFeeModel` requires guessing a fee; `MakerTakerFeeModel` reads the maker/taker rates that `load_binance_instruments()` already populated from the real `exchangeInfo` response — no guessing, and it is the "don't hand-roll a fee model" choice. |
| Default `FillModel()` (no args, no randomness) | `OneTickSlippageFillModel`/`LimitOrderPartialFillModel` (take `random_seed`) | The seeded models exist and are legitimate for later phases' realism (`SIM-03`, Phase 2), but Phase 1's determinism requirement (D-18, success criterion 2) is trivially satisfied by using the model with **no** randomness at all — no seed to pin, no RNG algorithm/version to worry about matching across "two machines." |

**Installation (illustrative — engine/ is a uv project per D-02):**
```bash
# From engine/, once the Nautilus submodule is checked out at <path>:
uv add --editable <path-to-submodule>/python  # registers `nautilus-trader` as a path dependency
uv add pydantic sqlalchemy psycopg[binary] pyarrow
uv add --dev pytest ruff datamodel-code-generator

# Rust + maturin must be present on PATH before the editable install resolves:
rustup toolchain install 1.98.0   # or whatever rust-toolchain.toml in the submodule pins
cargo install maturin --version 1.15.0 --locked
```

## Package Legitimacy Audit

| Package | Registry | Published (latest) | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|---------------------|-----------|-------------|---------|-------------|
| `nautilus_trader` | pypi (not installed from here — submodule instead) | 2026-09-02 (rc4) | — | github.com/nautechsystems/nautilus_trader | OK | Not installed from PyPI at all (D-04); audit is informational only |
| `datamodel-code-generator` | pypi | 2026-09-04 | unknown (checker limitation) | github.com/koxudaxi/datamodel-code-generator | SUS | Flagged — see note below |
| `polars` | pypi | 2026-08-26 | unknown (checker limitation) | pola.rs | SUS | Flagged — see note below |
| `pyarrow` | pypi | 2026-08-10 | unknown (checker limitation) | arrow.apache.org | SUS | Flagged — see note below |
| `duckdb` | pypi | 2026-07-22 | unknown (checker limitation) | github.com/duckdb/duckdb-python | SUS | Flagged — see note below |
| `import-linter` | pypi | 2026-09-04 | unknown, no repo URL returned | (none returned) | SUS | Flagged — optional dependency, not recommended (see Alternatives Considered) |
| `sqlalchemy` | pypi | 2026-08-11 | unknown (checker limitation) | sqlalchemy.org | SUS | Flagged — see note below |
| `json-schema-to-typescript` | npm | 2026-08-28 | 3,464,191/week | github.com/bcherny/json-schema-to-typescript | SUS | Flagged — see note below |
| `prisma` (CLI) | npm | 2026-09-04 | 17,048,010/week | github.com/prisma/prisma-cli | SUS | Flagged — see note below |
| `@prisma/client` | npm | 2026-08-25 | 16,077,029/week | github.com/prisma/prisma | SUS | Flagged — see note below |

**Note on the SUS verdicts above:** every one of these packages is flagged for the single reason
`too-new` (and, for PyPI packages, an additional `unknown-downloads`). Inspecting the actual signal
values shows why this is very likely a **checker false positive, not a real risk signal**: the
"published" date the checker used is each package's **most recent release**, not its founding date
— e.g. `@prisma/client` shows 16M weekly npm downloads and a `2026-08-25` "publish" date in the same
record (Prisma ships releases roughly weekly; that is a routine point release, not a new package).
The PyPI packages (`polars`, `pyarrow`, `duckdb`, `sqlalchemy`, `datamodel-code-generator`) all
resolved to their real, long-established GitHub/foundation source repos and simply lack a downloads
figure because the legitimacy checker has no PyPI download-count source wired up (`unknown-downloads`
is a checker gap, not evidence of low adoption). `import-linter` is the one package here with a
genuinely thin signal (no repo URL returned at all) — but it is not being recommended for use in this
phase (see Alternatives Considered), so this is moot unless a future phase reaches for it.

Per the package-legitimacy protocol, these are **not** removed (no `SLOP` verdicts appeared), but
**every package in this table should still get a `checkpoint:human-verify` task before its first
install**, exactly as the `SUS` disposition requires — the plan should not skip that step merely
because this research judges the underlying signal to be a checker artifact.

**Packages removed due to `[SLOP]` verdict:** none.
**Packages flagged as suspicious `[SUS]`:** all packages in the table above — planner must add
`checkpoint:human-verify` before each install, per protocol, despite the false-positive analysis.

## Architecture Patterns

### System Architecture Diagram

```
data.binance.vision (HTTPS, public, no auth)
        │  daily/monthly klines .zip + .zip.CHECKSUM
        ▼
┌─────────────────────────────┐        ┌──────────────────────────────┐
│ engine/data (ingestion)      │        │ GET /api/v3/exchangeInfo      │
│  - download zip + CHECKSUM   │        │ (public, no credentials)      │
│  - sha256 verify, hard-fail  │        └──────────────┬────────────────┘
│  - unzip, detect ts unit     │                       │ daily cron
│  - parse rows → Bar objects  │                       ▼
│    (Price.from_str, no float)│        ┌──────────────────────────────┐
└──────────────┬────────────────┘        │ GitHub Actions (scheduled)   │
               │ catalog.write_bars()     │  → hosted Postgres           │
               │ catalog.write_instruments│    symbol_listing_snapshot   │
               ▼                          │    (raw payload + columns)   │
┌─────────────────────────────┐          └──────────────────────────────┘
│ ParquetDataCatalog (S3)      │
│  bars + instruments          │
└──────────────┬────────────────┘
               │ BacktestDataConfig(catalog_path=...)
               ▼
┌───────────────────────────────────────────────────────────┐
│ BacktestNode / BacktestEngine  (nautilus_trader, stock v2)  │
│                                                               │
│  add_venue(BINANCE, CASH, MakerTakerFeeModel, FillModel())   │
│  add_strategy(DslStrategy(spec=StrategySpec.json))           │
│                                                               │
│  ┌─────────────────────────┐   ┌────────────────────────┐   │
│  │ engine/adapters/         │   │ engine/dsl/             │   │
│  │ dsl_strategy.py          │──▶│ evaluator.py            │   │
│  │ (Strategy subclass;      │   │ (pure: bars in,         │   │
│  │  on_start/on_bar; ONLY   │   │  signal out; ZERO       │   │
│  │  file importing both     │   │  nautilus_trader import)│   │
│  │  nautilus_trader + dsl)  │   └────────────────────────┘   │
│  └─────────────────────────┘                                 │
└──────────────┬────────────────────────────────────────────────┘
               │ engine.get_result() / generate_account_report()
               │ generate_positions_report()
               ▼
┌─────────────────────────────┐
│ engine/cli (post-run)        │
│  - canonicalize (sorted keys,│
│    decimal strings, no       │
│    wall-clock/host/run-id)   │
│  - sha256 → hash.txt          │
│  - write trades.parquet,      │
│    equity.parquet             │
│  - INSERT trials row          │──▶ Postgres (Prisma-migrated `trials`)
│    (SQLAlchemy Core, always,  │      via SQLAlchemy Core INSERT
│    even on crash/abort)       │
└─────────────────────────────┘
```

### Recommended Project Structure

```
engine/                      # uv project, Python 3.13 (D-02)
├── dsl/
│   ├── spec.py               # StrategySpec — imports ONLY generated Pydantic models
│   └── evaluator.py          # DslEvaluator — pure; zero nautilus_trader import
├── adapters/
│   └── dsl_strategy.py       # DslStrategy(Strategy) — the ONE file importing both
├── data/
│   ├── binance_vision.py     # download + CHECKSUM verify + CSV → Bar
│   └── exchange_info.py      # daily snapshot fetch + raw+extracted write
├── cli/
│   └── backtest.py           # `uv run backtest ...` entry point (D-17)
├── persistence/
│   └── trials.py             # SQLAlchemy Core Table() mirrors of Prisma-migrated tables
├── tests/
│   ├── dsl/                  # runs with a plain list of bars, NO nautilus_trader import path
│   └── determinism/          # runs the CLI twice, asserts hash.txt equality
├── pyproject.toml
└── package.json              # thin shim: "test" → `uv run pytest`, "lint" → `uv run ruff check`

schemas/
└── strategy-spec.v1.json     # source of truth (D-06) — hand-written, versioned

prisma/                       # extracted standalone workspace package (D-09)
└── schema.prisma             # owns `trials`, `symbol_listing_snapshot`, + existing auth models
```

### Pattern 1: Catalog-driven backtest via `BacktestNode` (not `BacktestEngine` directly)

**What:** Configure venues/data/engine as `BacktestRunConfig` objects and run through
`BacktestNode`, reading bars from a `ParquetDataCatalog` by path rather than constructing them
inline.
**When to use:** This is the "recommended path for production workflows" per the tutorial itself —
the same strategy class carries forward to `LiveNode` in later phases with no changes.
**Example:**
```python
# Source: docs/getting_started/backtest_high_level.py (verified in pinned submodule checkout)
from nautilus_trader.backtest import BacktestNode
from nautilus_trader.config import BacktestDataConfig, BacktestEngineConfig
from nautilus_trader.config import BacktestRunConfig, BacktestVenueConfig
from nautilus_trader.model import AccountType, OmsType
from nautilus_trader.persistence import ParquetDataCatalog

catalog = ParquetDataCatalog(str(CATALOG_PATH))  # or an s3:// path per D-23

venue_configs = [
    BacktestVenueConfig(
        name="BINANCE",
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,       # spot — not MARGIN
        starting_balances=["1000000 USDT"],
    ),
]
data_configs = [
    BacktestDataConfig(
        data_type="Bar",
        catalog_path=str(CATALOG_PATH),
        instrument_id=instrument.id,
        bar_spec=bar_type.spec,
        start_time=start_ns,
        end_time=end_ns,
    ),
]
config = BacktestRunConfig(venues=venue_configs, data=data_configs, engine=BacktestEngineConfig())
node = BacktestNode(configs=[config])
node.build()
node.add_strategy(config.id, DslStrategy(config=dsl_strategy_config))
results = node.run()
```
Note the venue is `CASH` account type for spot (`docs/getting_started/backtest_low_level.py` uses
this exact pattern against a simulated Binance venue), not `MARGIN` — `MARGIN`/`CryptoPerpetual` is
for futures, not spot.

### Pattern 2: `Strategy` lifecycle — `on_start`/`on_bar`, indicator registration

**What:** The `Strategy` subclass registers indicators against a `bar_type`, subscribes to bars,
and reacts per-bar.
**When to use:** This is the shape `DslStrategy` must have; `DslEvaluator` supplies the actual
cross-detection logic, called from `on_bar`.
**Example:**
```python
# Source: docs/tutorials/ema_cross.py (verified in pinned submodule checkout)
class DslStrategy(Strategy):
    def __init__(self, config: DslStrategyConfig) -> None:
        super().__init__(config)
        self.evaluator = DslEvaluator(config.spec)   # pure, from engine/dsl/

    def on_start(self) -> None:
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        signal = self.evaluator.on_bar(bar)          # ALL decision logic lives here, in engine/dsl/
        if signal == "ENTER_LONG" and self.portfolio.is_net_flat(self.config.instrument_id):
            instrument = self.cache.instrument(self.config.instrument_id)
            order = self.order_factory.market(
                self.config.instrument_id, OrderSide.BUY, instrument.make_qty(self.config.trade_size),
            )
            self.submit_order(order)
        elif signal == "EXIT" and self.portfolio.is_net_long(self.config.instrument_id):
            self.close_all_positions(self.config.instrument_id)

    def on_stop(self) -> None:
        self.close_all_positions(self.config.instrument_id)
```
`DslEvaluator.on_bar(bar)` here must accept a **plain data structure** (a dataclass or namedtuple
built from the Nautilus `Bar`'s own OHLCV fields, or the raw `Bar` object read purely for its
attributes without ever `import`ing `nautilus_trader` inside `engine/dsl/`) — the boundary is about
which **module** imports `nautilus_trader`, not about touching `Bar`-shaped data. The cleanest split:
`dsl_strategy.py` converts `Bar` → a plain `(open, high, low, close, volume, ts_event)` tuple/dataclass
defined in `engine/dsl/`, and `DslEvaluator` never sees a Nautilus type at all.

### Pattern 3: Direct `Bar` construction from Binance Vision CSV (no wrangler needed)

**What:** Parse each Binance Vision kline CSV row and construct a `Bar` directly.
**When to use:** Always, for Phase 1's 1h/handful-of-symbols volume.
**Example:**
```python
# Source: python/nautilus_trader/testkit/providers.py:562-599 (pattern verified in pinned checkout),
# combined with docs/concepts/data/bar.md's recommended from_str construction and D-24 (close-time convention)
from nautilus_trader.model import Bar, BarType, Price, Quantity

def parse_row(row: list[str], bar_type: BarType, price_precision: int, size_precision: int) -> Bar:
    open_time_raw, o, h, l, c, v, close_time_raw = row[0], row[1], row[2], row[3], row[4], row[5], row[6]
    unit_ns = 1_000 if len(open_time_raw) == 13 else 1  # ms→ns vs already-µs→ns; see Common Pitfalls
    close_time_ns = int(close_time_raw) * unit_ns
    return Bar(
        bar_type=bar_type,
        open=Price.from_str(o), high=Price.from_str(h), low=Price.from_str(l), close=Price.from_str(c),
        volume=Quantity.from_str(v),
        ts_event=close_time_ns,   # D-24: close-time convention, NOT open_time
        ts_init=close_time_ns,
    )
```
Prefer `Price.from_str`/`Quantity.from_str` (parses the decimal string exactly) over
`Price(float(x), precision=...)` — the latter is what Nautilus's own **test fixture** helper uses
(acceptable for test data, not for a production loader where FOUND-09's "no float touches a
monetary/quantity value" spirit should hold end to end).

### Anti-Patterns to Avoid

- **Hashing raw `.parquet` file bytes for the reproducibility contract (D-18):** Parquet's footer
  embeds a `created_by` field containing the writing library's version string (e.g.
  `"parquet-cpp-arrow version X.Y.Z"`) `[CITED: arrow.apache.org/docs/python/parquet.html]`. Two
  machines with different pyarrow patch versions would produce byte-different files with identical
  data. Hash a canonical re-serialization of the *data*, not the file.
- **Configuring `OneTickSlippageFillModel`/`LimitOrderPartialFillModel` "for realism" in Phase 1:**
  both take a `random_seed` parameter — any randomness source at all makes "byte-identical on
  two machines" depend on matching RNG algorithm and seed exactly. The plain `FillModel()` (Nautilus
  default, no args) has none of this. Defer realistic fill simulation to Phase 2 (`SIM-03`).
  `[VERIFIED: .../python/nautilus_trader/execution/__init__.pyi:151-204]`
- **Reflecting Prisma-migrated tables at import time via SQLAlchemy's `Table(..., autoload_with=...)`:**
  couples every `engine/` import to a live database connection and to Prisma's exact current column
  set. Declare the two tables' columns explicitly as SQLAlchemy Core `Table` objects mirroring the
  Prisma schema (see Architecture Pattern 4) — the two are then verified to match by a CI check that
  diffs the SQLAlchemy Core column list against `prisma db pull` output, not by runtime reflection.

### Pattern 4: Python writer against a Prisma-owned table (D-11)

**What:** SQLAlchemy Core `Table` objects, hand-declared to mirror the Prisma schema, used only for
`INSERT`/`SELECT` — never for migrations.
**When to use:** Every Python write to `trials` or `symbol_listing_snapshot`.
**Critical gotcha — Prisma ID defaults are client-side, not database-side:**
`@default(uuid())` / `@default(cuid())` generate the value inside the **Prisma Client** at insert
time; Postgres itself gets no `DEFAULT` clause for that column
`[CITED: prisma.io — "The UUID is only generated if you use Prisma Client to create records. If you
create records in any other way ... you must generate the UUID yourself."]`. This is exactly the
pattern the existing scaffold uses today —
`[VERIFIED: apps/server/prisma/schema.prisma:14 — id String @id @default(uuid())]` (same pattern on
`Session`, `Account`, `Verification`). A bare Python `INSERT INTO trials (...)` that omits `id` would
violate the `NOT NULL` primary-key constraint.
**Fix — use one of, for the two Phase 1 tables specifically:**
```prisma
// Source: prisma.io docs (context7), verified this session
model Trial {
  id String @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  strategyLineageId String
  paramsHash        String
  objective         String
  ranAt             DateTime @default(now())   // this one IS a real SQL DEFAULT CURRENT_TIMESTAMP
  wasOos            Boolean
  @@map("trials")
}
```
`@default(now())` for `DateTime` **does** compile to `DEFAULT CURRENT_TIMESTAMP` in the actual SQL
migration `[CITED: prisma.io docs example migration.sql — "createdAt" TIMESTAMP(3) NOT NULL DEFAULT
CURRENT_TIMESTAMP]` — so `ran_at` can safely be omitted from the Python `INSERT` and let Postgres
fill it, but `id` cannot.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Equity curve / trade list extraction | A custom event-log walker over `Cache`/`Portfolio` | `BacktestEngine.generate_account_report()` (balances over time → equity curve) + `generate_positions_report()`/`generate_order_fills_report()` (trade list) | Already implemented, already returns decimal-string balances `[VERIFIED: python/nautilus_trader/analysis/reporter.py:187-225]` |
| Binance spot fee simulation | A hardcoded 0.1% constant | `MakerTakerFeeModel()` on the venue, fed by the instrument's real maker/taker rates from `load_binance_instruments()` | No guessing; uses the actual per-symbol rate the exchange reports |
| CSV → Bar aggregation for pre-aggregated klines | A custom bar-aggregation pipeline | Direct `Bar(...)` construction per row (Pattern 3 above) | Binance Vision klines are already aggregated by the exchange — there is nothing to aggregate, only to parse |
| Purity-boundary enforcement | `import-linter` config + custom CI rule | The literal `grep -rl nautilus_trader engine/dsl/` from success criterion 3 | The acceptance test **is** the enforcement mechanism; a second, different-shaped check adds drift risk between "what CI runs" and "what the roadmap promises" |
| JSON→Pydantic / JSON→TS contract sync | Hand-maintained parallel type definitions | `datamodel-code-generator` / `json-schema-to-typescript`, both against `schemas/strategy-spec.v1.json` | D-06 — this is the entire point of the schema-as-source-of-truth decision |

**Key insight:** almost everything Phase 1 needs from the engine side (report generation, fee
modeling, deterministic fills) already exists in stock Nautilus v2 and only needs to be *not
overridden* with something fancier — the discipline this phase requires is restraint, not
construction.

## Common Pitfalls

### Pitfall 1: Binance Vision kline timestamp unit silently changes mid-history

**What goes wrong:** A loader written and tested against 2024 data (13-digit millisecond
`open_time`/`close_time` values) silently misinterprets 2025+ data (16-digit microsecond values) as
milliseconds — producing timestamps 1000x too large, which either crashes far downstream or (worse)
silently produces bars dated in the year 3000+, breaking every full-history ingest for a symbol
listed before 2025.
**Why it happens:** Binance switched public data files to microsecond timestamps starting
2025-01-01, with **no schema version marker, no header row change, no filename change** — the CSV
shape (12 columns, no header) is byte-identical in structure across the boundary.
**Evidence (live falsification, this session):**
```
2024-12-01 → open_time=1733011200000     (13 digits, milliseconds)
2025-01-01 → open_time=1735689600000000 (16 digits, microseconds)
```
`[VERIFIED: live fetch of https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1h/
BTCUSDT-1h-{2024-12-01,2025-01-01}.zip, this session]`, corroborated by Binance's own changelog:
"The timestamp for SPOT Data from January 1st 2025 onwards will be in microseconds."
`[CITED: developers.binance.com/docs/binance-spot-api-docs/CHANGELOG]`
**How to avoid:** Detect the unit **per file** by digit count (13 → ms, 16 → µs) rather than
assuming a global constant; do not rely on the date in the filename alone (a file that spans a
timezone boundary or a late-published historical backfill could in principle be inconsistent —
digit-count detection is self-describing and immune to that).
**Warning signs:** Any bar with a `ts_event` implying a date far outside `[from, to]`; a full-history
ingest for a pre-2025-listed symbol where bars "jump" to nonsensical future dates partway through.

### Pitfall 2: `Position.to_dict()["signed_qty"]` is a raw float, everything else money-shaped is a string

**What goes wrong:** A persistence path that does `position.to_dict()` and writes the whole dict to
Parquet/Postgres lets a float into a `Position`-derived table, violating `FOUND-09`'s spirit even
though Nautilus's `OrderFilled`/`AccountBalance`/`MarginBalance` dicts are all decimal strings.
**Why it happens:** `signed_qty` is computed as `self.signed_qty.to_f64()` in the Rust `py_to_dict`
implementation — a real, deliberate exception, not an oversight (Nautilus's own
`ReportProvider.generate_positions_report` immediately deletes this column before returning the
report, alongside `quote_currency`/`base_currency`/`settlement_currency`).
**Evidence:** `[VERIFIED: crates/model/src/python/position.rs:457 — dict.set_item("signed_qty",
self.signed_qty.to_f64())?]`; `[VERIFIED: python/nautilus_trader/analysis/reporter.py:176-178 — for
col in ("signed_qty", ...): if col in report.columns: del report[col]]`
**How to avoid:** Always go through `generate_positions_report()`/`generate_order_fills_report()`
rather than calling `.to_dict()` on domain objects directly; if a future phase needs a field the
report generator drops, add an explicit, reviewed re-derivation rather than passing the raw dict
through.
**Warning signs:** A money-guard test (see Code Examples) that walks a persisted Parquet/JSON
structure for `float` values and finds one under a `signed_qty`-shaped key.

### Pitfall 3: `datamodel-code-generator`'s "decimal" support targets `number`-typed schemas, not `string`-typed ones

**What goes wrong:** The natural-looking choice — declare money fields as
`{"type": "number", "multipleOf": 0.00000001}` in `schemas/strategy-spec.v1.json` and pass
`--use-decimal-for-multiple-of` — does generate a Pydantic `condecimal(...)`, but the JSON Schema
`type` is still `"number"`. `json-schema-to-typescript` then emits a plain TS `number` for that same
field, which is exactly the JS-float representation D-07 requires the TS side to avoid
(string-or-bigint, never `number`).
**Why it happens:** `datamodel-code-generator`'s only documented decimal-generation trigger
(`--use-decimal-for-multiple-of`) is keyed off `"type": "number"` with a `multipleOf` constraint
`[CITED: koxudaxi.github.io/datamodel-code-generator docs/cli-reference/typing-customization.md]` —
there is no equivalent documented flag that maps a `"type": "string", "pattern": "^-?\d+(\.\d+)?$"`
field to `Decimal` on the Python side while still emitting `string` on the TS side.
**How to avoid:** Declare money fields as `"type": "string"` with a decimal-pattern regex (this gets
`json-schema-to-typescript` to emit `string`, correctly, for free) and accept that the *generated*
Pydantic field will be a plain `str`, then add one explicit, hand-written conversion step — a small
wrapper module (not the generated file) that calls `Decimal(value)` on the specific known money-field
names after `datamodel-code-generator` produces the model, or a Pydantic `field_validator` added via
a `--custom-template-dir` post-processing hook. This needs to be spiked, not guessed — see Open
Questions.
**Warning signs:** Generated Pydantic model has `price: str` where a `Decimal` was expected, or the
build silently produces `condecimal` fields whose JSON Schema type is `number` (a schema-drift CI
check comparing `schemas/strategy-spec.v1.json`'s declared type against the generated TS type would
catch this immediately).

### Pitfall 4: Rust rebuild time is unmeasured and gates the whole engine workstream

**What goes wrong:** Planning workstream B (contracts, `DslEvaluator`, `DslStrategy`) without first
measuring the cold `make build-debug` time risks discovering — after tasks are already sequenced —
that the Rust compile is the actual bottleneck for iteration speed, not anything Python-side.
**Why it happens:** The submodule's `target/` directory is already 18 GB
`[VERIFIED: du -sh target → 18G, this session]`, confirming this is a large Rust workspace; `make
build-debug` runs `maturin develop --profile <CARGO_CI_PROFILE>`
`[VERIFIED: Makefile:325-327]`, which compiles the full crate graph the first time.
**How to avoid:** Run `make build-debug` (or the equivalent `maturin develop` invocation) as a
dedicated, timed, week-1 task — exactly as PROJECT.md's tripwire 3 and the ROADMAP already require —
**before** sequencing any task that assumes a fast Python-Rust edit loop.
**Warning signs:** Any plan that puts `DslStrategy` adapter tasks on the critical path without a
prior "measure the build" task.

## Code Examples

### Money-guard test (Python) — the FOUND-09 enforcement mechanism

```python
# Source: pydantic docs (context7) — strict Decimal rejects float input with 'decimal_type' error
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, ValidationError

class MoneyField(BaseModel):
    model_config = ConfigDict(strict=True)
    amount: Decimal

def test_float_rejected_for_money_field():
    with pytest.raises(ValidationError, match="decimal_type"):
        MoneyField(amount=1.5)          # raw float — rejected in strict mode
    MoneyField(amount=Decimal("1.5"))   # Decimal instance — accepted
    MoneyField(amount="1.5")            # decimal string — accepted (this is the wire format, D-07)
```
`[VERIFIED via context7 /pydantic/pydantic: strict=True on a Decimal field raises 'decimal_type' when
given a float, whether or not the field carries additional constraints]`. Note: in *non-strict* mode
Pydantic v2 converts a float to `Decimal` via the value's exact string representation (not through an
IEEE-754 round-trip artifact) — so the risk this guard defends against is "a float reached the money
boundary at all" (contract violation), not silent precision loss, which pydantic v2 already avoids
`[VERIFIED via context7 /pydantic/pydantic test: Decimal validation of 1.1 (float) == Decimal('1.1')
exactly]`.

### Determinism test skeleton

```python
def test_backtest_is_byte_identical_on_rerun(tmp_path):
    run_backtest(symbol="BTCUSDT", spec="strategies/sma.json", out=tmp_path / "run1")
    run_backtest(symbol="BTCUSDT", spec="strategies/sma.json", out=tmp_path / "run2")
    assert (tmp_path / "run1" / "hash.txt").read_text() == (tmp_path / "run2" / "hash.txt").read_text()
```
The canonicalization step that produces `hash.txt` must exclude every field `BacktestResult` exposes
that varies per process: `[VERIFIED: python/nautilus_trader/backtest/__init__.pyi:207-245]` —
`machine_id`, `instance_id` (a random `UUID4`), `run_id`, `run_started`, `run_finished` are all
present on `BacktestResult` and are exactly the fields D-18 says must never enter the hash.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `TradingNode` (v1) | `LiveNode.builder(...)` (v2) | v2.0.0rc1+ | Not directly relevant to Phase 1 (backtest-only), but any code copied from a v1-era tutorial (the majority of what exists on the internet and in most LLM training data) will use the wrong class names throughout. |
| Binance Vision klines: millisecond timestamps | Microsecond timestamps | 2025-01-01, per-symbol data files (not an API version change) | See Pitfall 1 — this is the single most important, least-documented fact in this research. |
| `nautilus_trader` PyPI stable | `1.231.0` (v1, Cython, security-backports only) | v2 is RC-only on PyPI | Confirms D-04's submodule choice is not "ahead of" a stable release that could be used instead — there is no stable v2 wheel to fall back to. |

**Deprecated/outdated:** Any Architecture_Plan.md reference to a hand-built OMS/fill/fee model is
superseded — `MakerTakerFeeModel`, `FillModel`, and the account/position/report machinery already
exist in Nautilus and should be used as-is for Phase 1 (see Don't Hand-Roll).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `storage_options` on `ParquetDataCatalog` accepts standard fsspec/S3 credential keys (not a Nautilus-specific format) | Supporting stack table | If wrong, S3-backed catalog setup (D-23) needs a different credential-passing mechanism; low risk, easy to verify at implementation time against the actual constructor behavior |
| A2 | `rust-version = "1.98.0"` in `Cargo.toml` is the toolchain version CI/devcontainer should pin, not merely a Cargo-enforced floor | Standard Stack, Rust toolchain row | If the submodule's CI actually pins a different (likely newer) exact version via a `rust-toolchain.toml`, the devcontainer should match that file instead — confirm at implementation time; low risk since `rust-version` is a floor, not a ceiling, so building with a newer toolchain is safe |
| A3 | A hand-written wrapper/post-processing step (not a documented `datamodel-code-generator` flag) is the right way to get a strict-Decimal Python field from a string-typed JSON Schema money field | Pitfall 3, Open Questions | If a documented flag does exist and was missed, the plan may add unnecessary custom code; low risk (worst case is one extra small file), but confirm via the tool's own `--help` output before committing to the wrapper approach |

**If this table is empty:** N/A — see rows above; all other quantitative claims in this research
(timestamp format, API shapes, class signatures, Prisma defaults) were verified directly against
either the pinned submodule source, a live `data.binance.vision`/PyPI/npm fetch, or official
documentation via Context7 this session.

## Open Questions (RESOLVED at plan time)

> Each question below was closed by Phase 1 planning. Resolution trail:
> - **Q1** — RESOLVED as a spike, not an answer: `01-04-PLAN.md` Task 1 is a `checkpoint:decision`
>   requiring the generator to be run and its actual emitted types quoted before options are presented.
> - **Q2** — RESOLVED in `01-03-PLAN.md` Task 2: the pinned checkout's `rust-toolchain.toml` pins
>   channel `1.98.0`; the devcontainer pins that exact channel.
> - **Q3** — RESOLVED in `01-07-PLAN.md` Task 2: BTCUSDT, ETHUSDT, BNBUSDT, plus one symbol listed
>   2021 or later.


1. **How exactly should a JSON-Schema decimal-string field become a strict Python `Decimal` via the
   D-06 codegen pipeline?**
   - What we know: `datamodel-code-generator` has a documented decimal path for `"type": "number"`
     schemas (`--use-decimal-for-multiple-of`), which is the wrong JSON wire type for D-07's
     decimal-string requirement. No documented flag was found for `"type": "string"` → `Decimal`.
   - What's unclear: whether `--custom-template-dir` / a custom base class / a post-generation sed
     step is the intended mechanism, and which is least fragile against schema changes.
   - Recommendation: spend a half-day spike at plan time running
     `datamodel-codegen --input schema.json --input-file-type jsonschema --output-model-type
     pydantic_v2.BaseModel` against a minimal repro schema with a `"type": "string", "pattern":
     "..."` money field, and inspect the actual generated output before committing the plan to a
     specific mechanism. Flag this task explicitly as a spike, not a confident instruction.

2. **Exact CI-pinned Rust toolchain version, if it differs from `Cargo.toml`'s `rust-version` floor.**
   - What we know: `Cargo.toml:54` declares `rust-version = "1.98.0"` as a minimum.
   - What's unclear: whether a `rust-toolchain.toml` or CI workflow file pins something newer.
   - Recommendation: `grep` the submodule for `rust-toolchain.toml` and the `.github/workflows`
     directory's Rust setup step before finalizing the devcontainer image (D-10) — this is a two-
     minute check at implementation time, not deferred research.

3. **Where should the "handful of majors" beyond BTCUSDT be decided, and against what listing-date
   diversity criterion?**
   - What we know: D-21 leaves the exact symbol set to researcher/implementer discretion, motivated
     by wanting to surface bugs a single symbol hides (differing precision filters, mid-range
     delistings).
   - What's unclear: no delisted-by-2019 example symbol (like `SALTBTC`/`BCCBTC`, mentioned for
     Phase 2's universe test) was independently re-verified this session as still fetchable from
     Binance Vision — Phase 2 owns that verification, but Phase 1's "handful of majors" choice should
     lean toward symbols with materially different listing dates so the loader's generality (D-21:
     "symbol, interval, range are parameters") gets exercised now rather than only in Phase 2.
   - Recommendation: pick 3-4 of BTCUSDT/ETHUSDT/BNBUSDT plus one symbol listed noticeably later
     (e.g. a 2021+ listing) to force at least one genuinely different `from` boundary through the
     loader during Phase 1.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `uv` | Python packaging for `engine/` and the Nautilus submodule | ✓ (this session's dev machine) | 0.12.0 | — (already satisfies the `>=0.12,<0.13` pin) |
| Rust toolchain + `cargo` | Editable install of the Nautilus submodule | Not probed this session (no `cargo`/`rustc` check run) | — | Confirm at devcontainer build time; D-10 already plans to pin this |
| `maturin` | Building the Rust extension | Not probed this session | — | `cargo install maturin --version 1.15.0 --locked` per Standard Stack |
| Network access to `data.binance.vision` and `api.binance.com` | Data ingestion, `exchangeInfo` fetch | ✓ (verified live this session — successful HTTPS fetches, HTTP 200) | — | — |
| Network access to a hosted Postgres (Neon/Supabase/RDS, D-12 target) | Daily `exchangeInfo` cron | Not applicable to research session — provider not yet chosen | — | D-12 leaves provider choice to implementation; any of the three works with GitHub Actions |
| AWS credentials / S3 bucket | `ParquetDataCatalog` (D-23) | Not probed this session | — | A local-disk catalog is a valid interim fallback for solo development iteration (D-23's own "Planner note" already anticipates this) |

**Missing dependencies with no fallback:** none identified — every dependency this phase needs has
either been confirmed available or has an explicit, already-decided fallback in CONTEXT.md.

**Missing dependencies with fallback:** Rust toolchain/maturin/S3 credentials — all addressed by
D-10 (devcontainer) or D-23's local-cache note; confirm concretely during Wave 0 of execution rather
than blocking planning on it.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (Python side, `engine/`); no test framework exists yet for `engine/` — it does not exist as a directory yet |
| Config file | none yet — Wave 0 must create `engine/pyproject.toml`'s `[tool.pytest.ini_options]` (or a `pytest.ini`), copying the existing convention from `packages/fastapi-server/pyproject.toml` `[VERIFIED: apps/server and packages/fastapi-server directory listing, this session — packages/fastapi-server/pyproject.toml exists with an established uv+ruff+pytest convention per CONTEXT.md's Existing Code Insights]` |
| Quick run command | `uv run pytest engine/tests/dsl -q` (must run with `nautilus_trader` absent from the environment to prove success criterion 3's "no engine present" claim — see Wave 0 Gaps) |
| Full suite command | `uv run pytest engine/tests -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FOUND-05/FOUND-06 | `DslEvaluator` runs against a plain list of bars, zero Nautilus imports, under 1s | unit | `uv run pytest engine/tests/dsl -q` (run in a venv with `nautilus_trader` NOT installed, or via `python -S` guard) | ❌ Wave 0 |
| FOUND-09 | A float reaching a monetary field fails the build | unit | `uv run pytest engine/tests/test_money_guard.py -x` | ❌ Wave 0 |
| DATA-01 | Checksum mismatch hard-fails ingestion | unit | `uv run pytest engine/tests/data/test_binance_vision.py::test_checksum_mismatch_fails -x` | ❌ Wave 0 |
| DATA-06 | Bars are timestamped at close, asserted in tests | unit | `uv run pytest engine/tests/data/test_binance_vision.py::test_ts_event_is_close_time -x` | ❌ Wave 0 |
| SIM-01/SIM-02 | Backtest produces equity curve + trade list; identical input → identical output | integration | `uv run pytest engine/tests/determinism/test_reproducibility.py -x` (runs a real, small backtest twice) | ❌ Wave 0 |
| SIM-04 | Same `DslEvaluator` code path — enforced structurally by the architecture (only `DslStrategy` calls it), not by a separate test | structural/CI | `grep -rl nautilus_trader engine/dsl/` (success criterion 3, literal) | ❌ Wave 0 (CI step) |
| VALID-01 | A `trials` row is written on completion **and** on crash/abort | integration | `uv run pytest engine/tests/persistence/test_trials.py -x` (must include a forced-exception case) | ❌ Wave 0 |
| DATA-03 | Daily snapshot lands with no gaps | operational (cron), not unit-testable | manual `SELECT count(*) FROM symbol_listing_snapshot` growth check, per success criterion 4 | N/A — this criterion is inherently time-based, see note below |

### Sampling Rate
- **Per task commit:** `uv run pytest engine/tests/dsl -q` (fast, no engine)
- **Per wave merge:** `uv run pytest engine/tests -q` (full suite, engine present)
- **Phase gate:** Full suite green before `/gsd-verify-work`, **plus** a multi-day wait for
  `DATA-03`'s gapless-daily-count criterion — this criterion cannot be satisfied on the same day the
  code merges, no matter how correct the code is. The plan should schedule the cron's first deploy
  as early as possible in Wave 0 specifically so this waiting period runs concurrently with the rest
  of the phase's build, not after it.

### Wave 0 Gaps
- [ ] `engine/pyproject.toml` with `[tool.pytest.ini_options]` — no test framework exists for
      `engine/` yet (the directory itself doesn't exist)
- [ ] `engine/tests/conftest.py` — shared fixtures (a small synthetic list of bars for `DslEvaluator`
      unit tests, independent of any real ingested data)
- [ ] A CI job variant that runs `engine/tests/dsl` **without** `nautilus_trader` installed at all —
      the "no engine present" half of success criterion 3 is not provable by a test that merely
      avoids importing it while the package sits importable in the same environment; a separate,
      Nautilus-free virtualenv/CI job is the only way to prove the absence claim, not merely the
      avoidance claim
- [ ] `engine/tests/data/binance_vision_fixtures/` — small, checked-in sample CSVs for both the
      millisecond-era and microsecond-era shapes (Pitfall 1), so the unit-testable parsing logic
      never depends on live network access

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No user-facing auth surface in Phase 1 (CTRL-* is Phase 4) |
| V3 Session Management | No | N/A this phase |
| V4 Access Control | No | N/A this phase — no multi-user surface yet |
| V5 Input Validation | Yes | `StrategySpec` JSON Schema validation on load (basic type/shape checking via generated Pydantic model — the *semantic* DSL validator with rejection messages is DSL-02, Phase 2; Phase 1 only needs "malformed spec fails to parse," not "ambiguous spec is rejected with a helpful message") |
| V6 Cryptography | Yes | D-16's secrets manager (AWS Secrets Manager or equivalent) for the hosted-Postgres credential used by the `exchangeInfo` cron and local dev — never hand-roll credential storage, use the platform's secrets manager SDK directly |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Corrupted/tampered Binance Vision data silently accepted | Tampering | D-25's hard-fail on CHECKSUM mismatch, verified this session to be a real, working sha256 sidecar (`shasum -a 256` of a downloaded file matched the published `.CHECKSUM` content exactly, this session) |
| Credential leakage for the hosted-Postgres cron target | Information Disclosure | D-16 — secrets manager from day one, not `.env` files committed or passed as GitHub Actions plaintext secrets beyond the platform's own encrypted-secrets mechanism |
| SQL injection via SQLAlchemy Core string-built queries | Tampering | Use SQLAlchemy Core's parameterized `insert()`/`select()` constructs, never raw string interpolation, for the `trials`/`symbol_listing_snapshot` writer |

## Sources

### Primary (HIGH confidence)
- Pinned NautilusTrader v2 submodule checkout — `/Users/criox4/Codes/Trade_Platform/Nautilus_Engine
  /nautilus_trader` @ `be9eaff8a7f50ec72dd54cd0cd894fdc127e69bf` (`v2.0.0rc4`), read directly this
  session: `python/nautilus_trader/backtest/__init__.pyi`, `python/nautilus_trader/persistence/
  __init__.pyi`, `python/nautilus_trader/model/__init__.pyi`, `python/nautilus_trader/execution/
  __init__.pyi`, `python/nautilus_trader/adapters/binance/__init__.pyi`,
  `python/nautilus_trader/analysis/reporter.py`, `python/nautilus_trader/testkit/providers.py`,
  `docs/getting_started/backtest_high_level.py`, `docs/getting_started/backtest_low_level.py`,
  `docs/tutorials/ema_cross.py`, `docs/concepts/data/bar.md`, `docs/concepts/data/index.md`,
  `docs/integrations/binance.md`, `python/tests/unit/adapters/binance/test_binance_migration.py`,
  `crates/model/src/python/position.rs`, `crates/model/src/python/types/balance.rs`,
  `crates/model/src/python/events/order/filled.rs`, `python/pyproject.toml`, `Cargo.toml`, `Makefile`
- Live `data.binance.vision` HTTPS fetches this session — daily/monthly klines and `.CHECKSUM`
  sidecars for BTCUSDT 1h, spanning 2017-08-17 through 2025-06-01, including the exact
  millisecond→microsecond boundary (2024-12-01 vs 2025-01-01)
- `crates/adapters/binance/test_data/spot/http_json/exchange_info_response.json` (in-repo fixture,
  read this session) — real `GET /api/v3/exchangeInfo` response shape
- PyPI JSON API (`nautilus_trader`, `datamodel-code-generator`, `maturin`, `import-linter`) — live
  queries this session
- npm registry (`json-schema-to-typescript`, `prisma`, `@prisma/client`) — live queries this session
- This repo's actual `apps/server/prisma/schema.prisma` and `apps/server/package.json` — read
  directly this session

### Secondary (MEDIUM confidence)
- Context7 `/prisma/web` — `@default(uuid())`/`@default(cuid())` client-side generation,
  `@default(dbgenerated("gen_random_uuid()"))` database-side alternative, `@default(now())` compiling
  to `DEFAULT CURRENT_TIMESTAMP`
- Context7 `/pydantic/pydantic` — strict-mode `Decimal` field rejecting float input
  (`decimal_type` error), and non-strict float→Decimal exact-string conversion behavior
- Context7 `/koxudaxi/datamodel-code-generator` — `--use-decimal-for-multiple-of`,
  `--strict-types` flags and their generated output shapes
- Context7 `/bcherny/json-schema-to-typescript` — CLI invocation, `additionalProperties` default
  behavior
- Binance official changelog (via WebSearch, corroborating the live-fetch finding) —
  microsecond-timestamp migration for spot public data from 2025-01-01

### Tertiary (LOW confidence)
- Prior-session `.planning/research/STACK.md`/`PITFALLS.md` claims not independently re-verified
  this session (e.g., `pydantic` 2.13.5, `polars` 1.44.1 exact versions) — carried forward as-is,
  tagged `[CITED: STACK.md prior research]` throughout rather than re-stated as newly verified

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every version-sensitive claim about the Nautilus v2 API and Binance Vision
  data format was checked against the pinned submodule source or a live fetch this session, not
  training memory
- Architecture: HIGH — the catalog-driven `BacktestNode` pattern and the `Strategy` lifecycle come
  directly from the pinned submodule's own tutorials, which match this phase's stated shape closely
- Pitfalls: HIGH for the timestamp-unit and Position.signed_qty findings (both directly observed);
  MEDIUM for the Prisma-defaults and codegen-decimal findings (verified against official docs, not
  against this specific schema's actual generated migration, which does not exist yet)

**Research date:** 2026-09-06
**Valid until:** 30 days for the Prisma/codegen/Pydantic findings (stable ecosystems); 7 days for
anything tied to the still-RC `nautilus_trader` v2 release train, since PROJECT.md itself notes
upstream is actively closing API gaps — re-verify the pinned commit's API surface if more than a
week elapses between this research and Wave 0 starting.
