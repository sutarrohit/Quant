# Stack Research

**Domain:** AI-first crypto quant trading platform (NautilusTrader engine + TS control plane + Python AI plane)
**Researched:** 2026-09-05
**Confidence:** HIGH for the engine plane (verified against the local checkout), HIGH for control plane (verified against pinned manifests + registries), MEDIUM for AI plane and validation tooling (ecosystem is immature; see gaps)

---

## Finding zero: the fork is on NautilusTrader **v2**, not v1

This changes every downstream recommendation and contradicts the framing of the research question.

| Fact | Evidence |
|------|----------|
| The fork's HEAD is `be9eaff8a7` merging `origin/develop` into `multi-tenant-nautilus-runtime` | `git log` in `/Users/criox4/Codes/Trade_Platform/Nautilus_Engine /nautilus_trader` |
| `origin/develop` is now **v2.0.0rc4** — a Rust-native PyO3 rewrite that replaced the Cython v1 package | `version.json` → `"v2.0.0rc4"`; `python/pyproject.toml` → `version = "2.0.0rc4"`, `build-backend = "maturin"` |
| There is **no `pyproject.toml` at the repo root**. The Python package moved to `python/` | `ls` of repo root |
| `TradingNode` **does not exist in v2**. It is `LiveNode`, built via `LiveNode.builder(name, trader_id, environment)` | `MIGRATION_V2.md:44`; `python/nautilus_trader/live/__init__.pyi:355-400` |
| v1 lives on `origin/develop_v1` and receives **critical security backports only, for ~3 months** after the v2 cutover | `MIGRATION_V2.md:5-7` |
| PyPI stable is `nautilus_trader==1.231.0` (v1 Cython). v2 exists only as `2.0.0rc1..rc4`, rc4 uploaded 2026-09-02 | PyPI JSON API |

**Recommendation: stay on v2.** The tenancy patch (`768cbf3664`) is written against v2 Rust crates — `crates/live/src/tenant.rs`, `crates/common/src/tenant.rs`, `crates/common/src/msgbus/`, `crates/system/src/kernel.rs`. v1's Cython execution path has no structural equivalent, so retargeting to `develop_v1` means discarding the single existing asset and then inheriting an EOL branch. Accept RC risk; pin an exact commit, not a tag.

**Consequence for PROJECT.md:** Every Nautilus API name in Architecture_Plan and in any v1-era tutorial is wrong. Budget a "v1 examples on the internet do not apply" tax on every engine task. `MIGRATION_V2.md` (47KB, in-repo) is the authoritative rename table — treat it as required reading for the engine phase, not the upstream website.

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **NautilusTrader (fork)** | `2.0.0rc4` @ pinned commit | Execution + backtest engine | Locked by PROJECT.md. v2 is the only branch the tenancy patch applies to. Same code path backtest↔live is structural, not a claim. |
| **Rust toolchain** | `1.98.0` (pinned) | Engine build | `rust-toolchain.toml` pins it exactly. Do not float; maturin + PyO3 ABI is version-sensitive. |
| **Python (engine + AI plane)** | `3.13` | Strategy runtime, AI plane | Nautilus v2 requires `>=3.12,<3.15` (`python/pyproject.toml`). `packages/fastapi-server` already pins `>=3.13`. 3.14 is supported by Nautilus but the LangChain/LangGraph wheel ecosystem lags — 3.13 is the boring choice. |
| **uv** | `>=0.12,<0.13` | Python packaging (both Python services) | Hard requirement of the Nautilus build (`python/pyproject.toml` → `[tool.uv] required-version`). Already used by `packages/fastapi-server`. One packaging tool across both Python services. |
| **PostgreSQL** | 17 | Product ledger, mandates, approvals, audit, outbox | Locked by PROJECT.md ("Postgres is the product ledger"). Also usable as Nautilus's own cache backend — `PostgresCacheConfig` is exposed to Python (`python/nautilus_trader/infrastructure/__init__.pyi:19`). |
| **Redis** | 7.4+ | Nautilus cache + msgbus backing, engine↔control-plane seam | Not optional. `MessageBusConfig(external_streams=[...], streams_prefix=..., stream_per_topic=...)` (`python/nautilus_trader/common/__init__.pyi:224-268`) is the *supported* way to get execution events out of the engine and commands in. This is the integration boundary, not a cache. |
| **Hono** | `4.13.7` (repo has `4.12.23`) | Control plane HTTP | Already scaffolded. Minor bump only. |
| **@hono/zod-openapi** | `1.6.3` (repo has `1.4.0`) | Typed routes + OpenAPI | Already scaffolded. Feeds contract generation (see Contracts below). |
| **Zod** | `4.5.4` (repo has `4.3.6`) | Contract source of truth | Zod 4 ships `z.toJSONSchema()` natively — this is what makes the Zod-first contract strategy viable without a third-party converter. |
| **Prisma** | **stay on `7.8.x`** | Postgres ORM/migrations | `8.0.0-rc.13` is the current npm `latest` tag and is a release candidate. Do not run two RCs (Nautilus v2 + Prisma 8) in one system. |
| **better-auth** | `1.7.2` (repo has `1.6.20`) | Auth, sessions, tenancy hook | Already scaffolded with its four tables in `apps/server/prisma/schema.prisma`. |
| **Next.js / React** | `16.3.4` / `19.2.4` | Web UI | Already scaffolded. |
| **pnpm / Turborepo** | `10.34.5` / `2.10.7` | Monorepo | Already scaffolded. |
| **pg-boss** | `12.30.0` | Transactional-outbox consumer + job layer | **Replaces Architecture_Plan's BullMQ.** See below. |
| **LangGraph** | `1.2.11` (with `langchain-core 1.6.2`) | Research committee orchestration | Build the committee directly. See AI plane below. |
| **AWS KMS + AWS CDK** | `aws-cdk-lib 2.257.0` (already a devDep) | Envelope encryption for exchange credentials | CDK is already in `apps/server`. Adding Vault or GCP KMS means a second cloud for a two-person team. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `nautilus_trader.persistence.ParquetDataCatalog` | in-engine | Canonical market-data store for backtests | Always. Verified surface: `write_bars`, `write_trade_ticks`, `write_quote_ticks`, `write_instruments`, `consolidate_data_by_period`, `extend_file_name` (`python/nautilus_trader/persistence/__init__.pyi:101-200`). Takes `storage_options` → S3-backed catalogs work. |
| `polars` | `1.44.1` | Binance Vision CSV → Nautilus wrangler input | ETL for the historical loader. Faster and lower-memory than pandas for the multi-GB aggTrades zips. |
| `pyarrow` | `25.0.1` | Parquet interop with the catalog | Only where you need to read the catalog outside Nautilus. |
| `duckdb` | `1.5.5` | Ad-hoc queries over the Parquet catalog | Data-quality monitors (gap detection, outlier flagging) run as DuckDB SQL over the catalog. Zero infra. |
| `datamodel-code-generator` | `0.76.2` | JSON Schema → Pydantic models | Contract generation for the Python side. |
| `pydantic` | `2.13.5` | Python-side contract validation | Generated target. Note: Nautilus v2 configs are PyO3 `@final` types, **not** Pydantic — do not try to unify them. |
| `msgspec` | latest | Redis-stream (de)serialization at the engine seam | Nautilus's own `SerializationEncoding` is MsgPack or JSON. msgspec decodes both, fast, with typed structs. |
| `pino` | `10.3.1` (present) | Structured logs with redaction | Configure `redact` paths for `apiKey`/`apiSecret`/`dek` on day one, not later. |
| `@aws-sdk/client-kms` | latest v3 | `GenerateDataKey` / `Decrypt` | Envelope encryption. |
| `node:crypto` AES-256-GCM | stdlib | DEK-side encryption | Do **not** add a crypto library. `crypto.createCipheriv('aes-256-gcm', dek, iv)` is the whole implementation. |
| `numpy` + `scipy` | latest | Deflated Sharpe / PBO / Monte Carlo | You are writing these. See validation section. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `make build-debug` (Nautilus) | Build the fork | Uses the **root** `.venv` and `target/`. The local `target/` is currently **18 GB**. Provision disk accordingly; this is a real cost of the fork decision. |
| `maturin` | `1.15.0`, pinned exactly | Pinned in `python/pyproject.toml` build-system. `scripts/maturin-version.bash` reads the pin for CI. Do not float. |
| `ruff` | Python lint/format, both Python services | Already configured in `packages/fastapi-server/pyproject.toml`. Nautilus has its own `.ruff_cache`. |
| `vitest` | `4.1.7` (present) | TS tests |
| `sqlc`-style checked-in generated types | Contract codegen artifacts | Commit generated types; do not generate at build time. Generation drift must show up as a diff in review. |

---

## Answers to the specific questions

### 1. Nautilus embedding — how to operate the node

**Supported deployment shape (verified):** a long-running **Python process** that builds and runs one `LiveNode`. Canonical wiring, from `examples/live/binance/exec_tester.py:65-90`:

```python
node = (
    LiveNode.builder("BINANCE-EXEC-001", TraderId.from_str("..."), Environment.LIVE)
      .with_reconciliation(reconciliation=True)
      .with_risk_engine_config(LiveRiskEngineConfig(...))
      .with_cache_config(CacheConfig(...))          # Redis or Postgres backing
      .with_msgbus_config(MessageBusConfig(...))    # external_streams = the control-plane seam
      .add_data_client(None, BinanceDataClientFactory(), BinanceDataClientConfig(...))
      .add_exec_client(None, BinanceExecutionClientFactory(), BinanceExecutionClientConfig(...))
      .build()
)
node.add_strategy(DslStrategy(cfg))   # or add_strategy_from_config(ImportableStrategyConfig)
node.run()                            # or await node.run_async()
```

`LiveNode` also exposes `handle()` → `LiveNodeHandle` with `is_running`, `state` (`NodeState.IDLE|STARTING|RUNNING|SHUTTING_DOWN|STOPPED`) and `stop()`, plus `add_strategy_from_config`. That handle is the supervision primitive. (`python/nautilus_trader/live/__init__.pyi:355-455`)

**Redis backing:** `CacheConfig` and `MessageBusConfig` in `python/nautilus_trader/common/__init__.pyi`; backends `RedisCacheConfig`, `RedisMessageBusConfig`, `RedisMessageBusFactory`, `PostgresCacheConfig` in `python/nautilus_trader/infrastructure/__init__.pyi`. `MessageBusConfig.external_streams` + `streams_prefix` is how the TS control plane subscribes to execution truth and injects commands. **Use this, not a bespoke IPC.**

**Recommended service shape: `engine-runner` — a Python process per tenant-node.** Confidence: HIGH.

> **⚠️ Fork capability differs from PROJECT.md's Key Decision.** PROJECT.md decides "multi-tenancy inside one runtime rather than a process per tenant." The tenancy patch **does not yet make that reachable from Python.**
>
> - `git show --stat 768cbf3664` touches **no** file under `crates/pyo3/`. `TenantHost`, `TenantContext`, `TenantEnvelope`, `TenantId`, `TenantNamespace` have no PyO3 bindings. `grep -rn "tenant" crates/pyo3/src/ crates/live/src/python/` returns nothing.
> - The two Python-facing files the commit *does* touch hard-code the tenant away: `crates/infrastructure/src/python/redis/cache.rs` and `.../msgbus.rs` both gained literally `tenant_id: None, account_id: None`. **From Python, tenant-aware Redis namespacing is currently unreachable**, so two tenants in one process would share a Redis keyspace. That is exactly the isolation leak PROJECT.md calls the riskiest artifact.
> - `crates/live/src/tenant.rs:19-21` states `TenantHost` "is intentionally single-threaded: the underlying engines use `Rc<RefCell<_>>`." Multi-tenant hosting is therefore one OS thread, cooperatively scheduled with `TenantLimits` (`max_queue_depth: 10_000`, `max_open_orders: 10_000`, `max_strategies: 100`, `max_events_per_second: 100_000`).
> - What *does* work from Python today: the `MessageBusScope::enter` / `AsyncRunner::enter_scope` guards the patch added to every `LiveNode` entry point (`crates/live/src/node/mod.rs`, 9 call sites) remove the global-message-bus singleton assumption. That is the hard part, and it is done. Multiple `LiveNode` objects in one Python process is plausible *because of* that change.
>
> **Ship v1 as one `LiveNode` per process per tenant.** It satisfies every functional requirement, is the shape upstream tests, and is the only shape whose Redis isolation is provable today. Treat the single-runtime multi-tenant host as a later optimisation gated on (a) PyO3 bindings for `TenantHost`, or (b) plumbing `tenant_id` through the Python Redis configs. Reaching for it in v1 converts PROJECT.md tripwire #1 into a certainty.

### 2. Binance spot adapter maturity — **mature.** Confidence: HIGH

~140,000 lines of Rust across `crates/adapters/binance/`, with per-product test suites (`tests/spot/{http,websocket_streams,websocket_trading,exec_client,data_client}.rs`) and runnable examples. Verified from `docs/integrations/binance.md`:

| Capability | Spot status |
|---|---|
| `MARKET`, `LIMIT` | ✓ (MARKET supports quote-quantity, spot only) |
| `STOP_MARKET` / `STOP_LIMIT` | ✓ (sent as `STOP_LOSS` / `STOP_LOSS_LIMIT`) |
| `MARKET_IF_TOUCHED` / `LIMIT_IF_TOUCHED` | ✓ (sent as `TAKE_PROFIT` / `TAKE_PROFIT_LIMIT`) |
| `TRAILING_STOP_MARKET` | ✗ futures only |
| `post_only` | ✓ on `LIMIT` only, via `LIMIT_MAKER` |
| `reduce_only` | ✗ futures only |
| TIF | `GTC`, `IOC`, `FOK` native; **`GTD` is a local emulation over `GTC`** — spot has no venue `goodTillDate` |
| WebSocket execution reports | ✓ user-data stream; optional WebSocket *trading* API via `use_ws_trading` |
| Startup reconciliation | ✓ `generate_order_status_reports`, `generate_fill_reports`, `generate_position_status_reports`, `generate_mass_status` (`crates/adapters/binance/src/spot/execution.rs:1231-1600`) |
| Testnet | ✓ `BinanceEnvironment.TESTNET` → `testnet.binance.vision`. Docs call it "legacy" and steer new setups to `DEMO`, but **spot testnet remains on TESTNET**. |

**Two gotchas that will bite:**

1. **Ed25519 or nothing, soon.** The adapter signs with Ed25519 or HMAC-SHA256, auto-detected from secret format. **RSA is not supported. HMAC is deprecated and will be removed.** Worse: `spot_market_data_mode` defaults to `Sbe`, and **SBE requires Ed25519 and refuses to connect without it**. Set `spot_market_data_mode=Json` if you want credential-free public market data, and be aware Json mode is also *required* for real-time spot kline and `@ticker` streams (Binance does not publish those over spot SBE).
   → **The "API secret" is a multi-line unencrypted PKCS#8 PEM private key, not a 64-char string.** This changes the credential schema (text, not varchar(128)), the KMS ciphertext size, and the redaction rules. Design for it now.
2. **No local order-type validation.** "Binance Spot publishes a supported order-type set per symbol in `exchangeInfo`. The adapter does not filter on it, so a conditional Spot order for a type the symbol does not support is rejected by the venue rather than locally." Your DSL validator should enforce this, or Copilot previews will promise orders the venue rejects.

### 3. Market data — **`data.binance.vision`, free.** Confidence: HIGH (verified live)

Verified by direct S3 listing:
- `https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?prefix=data/spot/monthly/klines/BTCUSDT/1m/` → HTTP 200, monthly zips from `2017-08` forward, **each with a `.zip.CHECKSUM` sibling.**
- `data/spot/monthly/aggTrades/<SYM>/` → same shape.
- **Survivorship confirmed:** `SALTBTC`, `BCCBTC`, `MITHUSDT`, `TCTUSDT` — all delisted — still return keys. The archive is not pruned to the live symbol set.

**Cost:** $0. **Licensing:** Binance's own public archive of its own data; no per-seat vendor contract, no redistribution needed since you consume it into a private catalog.

**Path:** `data.binance.vision` (zip) → polars → Nautilus wranglers (`BarDataWrangler`, `TradeTickDataWrangler` in `python/nautilus_trader/persistence/__init__.pyi:26,407`) → `ParquetDataCatalog.write_bars` / `.write_trade_ticks` → backtest. One ingestion script, no vendor.

**What Nautilus does *not* give you:** there is no bulk `data.binance.vision` loader in the adapter. The only in-tree Binance historical loader is `load_binance_order_book_deltas(path, nrows)` for depth CSVs (`docs/integrations/binance.md:72-80`). The kline/aggTrades ingestion is yours to write — that is the Layer-0 work Quant-Phase budgets 8 weeks for.

**Point-in-time correctness** is not free from the archive. You must build:
- a `symbol_listing` table recording first/last seen date per symbol from the archive's own key listing (this is your PIT universe);
- restatement detection — re-download and checksum-compare a trailing window, because Binance does restate klines;
- gap detection — DuckDB SQL over the catalog is enough.

**Vendors — do not buy yet.** Tardis.dev is the right *later* answer if you need full L2/L3 book reconstruction or a normalized multi-venue feed; Nautilus already ships a first-class Tardis adapter (`crates/adapters/tardis/`, with `TardisHttpClient`, `TardisMachineClient`, `load_tardis_{trades,quotes,deltas,funding_rates}`, `run_tardis_machine_replay` — `python/nautilus_trader/adapters/tardis/__init__.pyi`), so adopting it later costs an ingestion script, not an architecture. Kaiko is institutional pricing for breadth you do not need at one venue. CryptoTick is not a stack you should take a dependency on for v1.

### 4. Time-series storage — **ParquetDataCatalog primary, Postgres secondary. Not ClickHouse, not TimescaleDB (yet).** Confidence: HIGH

For a two-person team, the deciding fact is that **the backtest engine reads the Parquet catalog natively.** Any other store is a second copy that can disagree with the one the simulator actually uses — which is precisely the "data that doesn't lie" failure Quant-Phase warns about.

| Need | Store |
|---|---|
| Backtest input (bars, trades, book) | `ParquetDataCatalog`, on local disk in dev, S3 in prod via `storage_options` |
| Ad-hoc analysis, data-quality monitors | DuckDB **over the same Parquet files** — zero copy, zero infra |
| UI charts, equity curves, timeline, per-trade slippage | Postgres (the product ledger you are already building) |
| Funding rates, OI | Not needed for spot v1 |

Add TimescaleDB **only** when a UI query over the ledger is measurably slow — it is a Postgres extension, so it is an `ALTER`, not a migration. **Skip ClickHouse entirely for v1:** it is a second database, a second backup story, and a second consistency question, in exchange for compression you do not need at one venue's spot history (Binance's entire BTCUSDT 1m archive since 2017 is a few GB).

This contradicts Architecture_Plan §15 ("TimescaleDB or ClickHouse … candles, trades, order-book snapshots, backtest time series") — that section predates the Nautilus decision and describes a store the engine cannot read.

### 5. Cross-language contracts — **Zod 4 → JSON Schema → Pydantic. No Protobuf. Rust needs nothing.** Confidence: MEDIUM-HIGH

The six frozen contracts (`StrategySpec`, `AgentMandate`, `TradeIntent`, `RiskDecision`, OMS boundary, reconciliation rules) are authored and enforced in TypeScript, because the control plane owns authorization truth (PROJECT.md Key Decision) and every one of them is written/validated by the control plane first.

```
packages/contracts/src/*.ts        (Zod 4 schemas — hand-written, the source of truth)
  └─ z.toJSONSchema()          →  contracts/jsonschema/*.json   (committed artifact)
       └─ datamodel-code-generator → services/ai/contracts/*.py (Pydantic v2, committed)
```

- **Zod-first, not JSON-Schema-first.** JSON Schema is not a pleasant authoring language and has no refinement story; Zod 4's `z.toJSONSchema()` is built in, so the "source of truth is a schema file" property is preserved without hand-writing JSON. TS gets types for free via `z.infer`. Runtime validation at the HTTP boundary already goes through `@hono/zod-openapi`, so the same schemas serve the API contract.
- **Commit the generated JSON Schema and Pydantic files.** Generation drift then appears as a reviewable diff. A CI job regenerates and fails on diff.
- **Rust needs nothing.** None of the six contracts crosses into Rust. The DSL evaluator is pure Python (PROJECT.md Key Decision); the Rust surface is Nautilus's own model types, which have their own serde. If a contract ever *does* need Rust, `typify` (oxidecomputer) compiles JSON Schema → Rust and slots into the same pipeline — but do not build that pipe before there is a consumer.
- **Reject Protobuf.** It buys wire efficiency and a schema registry you do not need at this throughput, costs a build-time codegen step in three languages, and cannot express the refinements (decimal-string format, cross-field constraints, discriminated unions) that these particular contracts are mostly *made of*. The engine seam is already MsgPack/JSON because that is what Nautilus's `SerializationEncoding` speaks.
- **Money stays a string everywhere.** JSON Schema `{"type":"string","pattern":"^-?\\d+(\\.\\d+)?$"}` → Zod `.regex()` → Pydantic `condecimal`/`str`. Never `number`. PROJECT.md constraint.

### 6. AI plane — **build the committee on LangGraph directly. Mine TradingAgents, do not depend on it.** Confidence: MEDIUM-HIGH

TradingAgents (TauricResearch) is real and healthy: 102,587 stars, Apache-2.0, `v0.4.0` released 2026-08-31, last push 2026-09-01, 362 open issues. But its `pyproject.toml` (fetched from `main`) disqualifies it as a **dependency**:

- `langchain-core>=0.3.81`, `langgraph>=0.4.8` — it targets the **pre-1.0 LangChain generation**. Current is `langchain-core 1.6.2` / `langgraph 1.2.11`. Adopting it pins your AI plane a major version behind.
- `yfinance`, `stockstats`, `backtrader` — it is **US-equities-shaped**. Its analyst tools fetch tickers and SPY-relative alpha. None of that applies to Binance spot.
- `[project.scripts] tradingagents = "cli.main:app"`, plus `questionary`, `rich`, `typer` — it is a **CLI research application**, not an embeddable library. `propagate()` is not an API surface with a stability contract.
- It brings its own `redis` and `langgraph-checkpoint-sqlite` persistence, which would collide with your engine's Redis and your Postgres.

> **⚠️ Supply-chain flag.** `pip install tradingagents` installs **version 0.7.0 published by `Mai0313`** (`Repository: https://github.com/Mai0313/tradingagents`) — a third-party fork, not TauricResearch's project, and with a *higher* version number than the official 0.4.0. If anyone on the team types `uv add tradingagents`, they get someone else's code. Install from the official git ref or not at all. Confidence: HIGH (verified against the PyPI JSON API).

**Do this instead:** build the research committee as your own LangGraph graph — `langgraph 1.2.11` + `langchain-core 1.6.2` — and lift TradingAgents' *design* (Apache-2.0, so lifting prompts and graph topology is legal and cheap): the analyst/researcher/trader/risk role split, the bull-vs-bear debate loop, structured output via `.with_structured_output(Schema)` on the decision nodes, and checkpointer-backed resume. Persist checkpoints to your **Postgres**, not sqlite. The committee's only output is an `AgentMandate`/`SignalCandidate` artifact validated against the frozen contract — which is exactly why owning the graph matters: you control the output schema.

This also matches PROJECT.md's sequencing decision (AI planes behind the deterministic spine) — a LangGraph graph you own can ship in slices; a forked CLI cannot.

### 7. Secrets — **AWS KMS + envelope encryption in `node:crypto`. Not Vault.** Confidence: HIGH

`apps/server` already carries `aws-cdk-lib` and CDK deploy scripts. Adding HashiCorp Vault means a stateful HA service two people must operate, seal/unseal, and back up; GCP KMS means a second cloud. Neither buys anything over KMS for this threat model.

```
per exchange account:
  KMS GenerateDataKey(KeySpec=AES_256, KeyId=<CMK>, EncryptionContext={tenantId, accountId})
    → { Plaintext: DEK, CiphertextBlob: wrappedDEK }        wrappedDEK stored in Postgres
  AES-256-GCM(DEK, secretPEM) → { iv, ciphertext, authTag } stored in Postgres
  zero the plaintext DEK

on execution:
  engine-runner (private subnet, its own IAM role) → kms:Decrypt(wrappedDEK, same EncryptionContext)
    → AES-256-GCM decrypt → plaintext PEM handed to BinanceExecutionClientConfig(api_secret=...)
    → never written to disk, never logged
```

Non-negotiables, all cheap:
- **`EncryptionContext = {tenantId, accountId}`** on both `GenerateDataKey` and `Decrypt`. This is KMS's built-in authenticated-associated-data — it makes a stolen `wrappedDEK` useless against a different account and gives you the tenant binding *in CloudTrail*.
- **`kms:Decrypt` is granted to the `engine-runner` role only.** The AI plane's role and the API role have no KMS action at all. That is the enforcement of Architecture_Plan §16's permission table, and it is an IAM policy, not code.
- **`pino` `redact` config** listing `apiSecret`, `api_secret`, `dek`, `plaintext` before the first credential is ever stored.
- No crypto library. `crypto.createCipheriv('aes-256-gcm', ...)` plus `@aws-sdk/client-kms` is the entire implementation — roughly 40 lines.
- The credential column must hold a **multi-line PEM** (see §2), so size it as `text` and make the ciphertext envelope a JSONB `{v, iv, tag, ct, wrappedDek}`.

### 8. Job/queue layer — **pg-boss `12.30.0`. Not BullMQ.** Confidence: HIGH

Architecture_Plan §18 recommends "PostgreSQL transactional outbox + BullMQ/Redis workers". That combination is self-defeating: the entire point of the outbox is that the enqueue commits **in the same transaction** as the state change, and BullMQ's enqueue is a Redis write — a dual write with a window in which the order row exists and the job does not. pg-boss enqueues inside your Postgres transaction and dequeues with `SELECT … FOR UPDATE SKIP LOCKED`. The outbox pattern *is* pg-boss's native model rather than something bolted onto it.

Secondary reasons: you already need Redis for Nautilus's cache/msgbus, and you do **not** want the fund-affecting job queue sharing a memory-bounded eviction-capable store with the engine's hot path. Architecture_Plan itself says "Do not make the monetary order state dependent solely on BullMQ, Redis, or Temporal history" — pg-boss is the way to obey that rule by construction. Throughput is a non-issue: Copilot mode requires a human tap per order.

Keep BullMQ in reserve for non-fund-affecting fan-out (notifications, evidence-bundle rendering) *only if* pg-boss proves inadequate, which it will not at this volume. Temporal stays out of scope per PROJECT.md.

### 9. Overfitting / validation tooling — **write it. There is no library to adopt.** Confidence: MEDIUM

This is the honest finding, and it is worth flagging to the roadmap as a gap rather than a stack choice.

| Need | Existing option | Verdict |
|---|---|---|
| Probability of Backtest Overfitting (CSCV) | `esvhd/pypbo` | Unmaintained, no releases, small. **Read it, don't import it.** |
| Deflated Sharpe Ratio | none maintained | Bailey & López de Prado (2014) closed form. ~40 lines of `scipy.stats`. |
| Walk-forward | `vectorbt` PRO splitters | Commercial, and pulls in a whole second backtest engine you rejected. **No.** |
| Monte Carlo trade reordering | none | ~20 lines of `numpy` over the trade list. |
| Purged / combinatorial CV | `mlfinlab` lineage | License-encumbered and heavy. Reimplement the splitter. |

**Build `packages/validation/` (Python, numpy + scipy) as a first-class deliverable.** It is a few hundred lines, it is the product differentiator Quant-Phase identifies ("selling the opposite — your strategy is probably overfit, here's the evidence"), and every candidate library would be a dependency on unmaintained code sitting on the path between a user and their own money. The load-bearing part is not the math — it is the **trial counter**: DSR is only honest if every optimization attempt increments N, which means the count lives in your strategy registry, not in a library.

Nautilus supplies the inputs (`nautilus_trader.analysis`, `Portfolio.statistics()`, `snapshots()` — `MIGRATION_V2.md`), so you get returns and trade lists without instrumenting anything.

### 10. What NOT to use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **CCXT / CCXT Pro** | Superseded by the Nautilus Binance adapter (PROJECT.md Key Decision). Architecture_Plan §11 is 100 lines of connection-manager, capability-registry and adapter design that `crates/adapters/binance/` already implements in 140k lines of tested Rust. | `BinanceDataClientFactory` / `BinanceExecutionClientFactory` |
| **A TypeScript OMS / order state machine** | Two systems that disagree about positions. Architecture_Plan §§9,10,12,13 are requirements on the *boundary and ledger*, not a build list. | Nautilus `LiveExecutionEngine` + Postgres mirror |
| **`TradingNode`, `nautilus_trader.live.node`, `BacktestEngine` from `.backtest.engine`** | v1 API. Does not exist in the fork. Every v1 tutorial, blog post and LLM completion will hand you these. | `LiveNode`, `nautilus_trader.backtest.BacktestNode`. Rename table: `MIGRATION_V2.md` |
| **NautilusTrader v1 / `develop_v1` / PyPI `1.231.0`** | EOL (~3mo of security backports). The tenancy patch does not apply to it. | v2 @ pinned commit |
| **Installing both v1 and v2** | Both install and import as `nautilus_trader`. Silent, catastrophic. | One venv per version; never both (`MIGRATION_V2.md:9-10`) |
| **ClickHouse** | Second database, second backup story, for compression a single-venue spot archive does not need. Cannot be read by the backtest engine. | `ParquetDataCatalog` + DuckDB |
| **TimescaleDB (in v1)** | Same — a second copy of data the simulator does not read. It is a Postgres extension, so adding it later is an `ALTER`. | Postgres for the ledger; add Timescale when a UI query is measurably slow |
| **BullMQ for the outbox** | Redis enqueue outside the Postgres transaction = dual write on the fund-affecting path. | `pg-boss` |
| **Kafka, Temporal** | Explicitly out of scope in PROJECT.md. | Postgres outbox + pg-boss |
| **`tradingagents` from PyPI** | Version 0.7.0 there is a **third-party fork by `Mai0313`**, not TauricResearch. Higher version number than the real project's 0.4.0. | Don't install it. Build on `langgraph 1.2.11` |
| **TradingAgents as a runtime dependency** | Pins `langchain-core 0.3.x` (a major version behind), is US-equities shaped (`yfinance`, `stockstats`, `backtrader`), and is a Typer CLI, not a library. | Own LangGraph graph; lift its design under Apache-2.0 |
| **Prisma 8** | `8.0.0-rc.13` is the current npm `latest` tag and is an RC. One RC per system (you already have Nautilus v2 rc4). | Stay on `7.8.x` |
| **RSA exchange keys** | Not supported by the adapter at all. | Ed25519 (PKCS#8 PEM, unencrypted) |
| **HMAC exchange keys** | Deprecated; will be removed. Also blocks spot SBE market data entirely. | Ed25519 |
| **`pypbo`, `mlfinlab`, `vectorbt` PRO** | Unmaintained / license-encumbered / drags in a second backtest engine. On the path between a user and their own money. | Own `packages/validation/` on numpy + scipy |
| **`float` for money anywhere** | PROJECT.md constraint. Nautilus's own `Price`/`Quantity`/`Money` are fixed-precision; JSON contracts use decimal strings. | `Decimal`, decimal strings |
| **A crypto library for envelope encryption** | `node:crypto` AES-256-GCM plus `@aws-sdk/client-kms` is ~40 lines. | stdlib |
| **HashiCorp Vault / GCP KMS** | A stateful HA service or a second cloud, for two people, when CDK+KMS is already in the repo. | AWS KMS |
| **A bespoke engine↔control-plane IPC** | `MessageBusConfig.external_streams` over Redis Streams is the supported, tested seam. | Redis Streams via `MessageBusConfig` |

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Nautilus v2 (`2.0.0rc4`) | Nautilus v1 (`1.231.0`) | Only if v2 RC instability triggers PROJECT.md tripwire (2) or (4) *and* the tenancy patch can be abandoned. Costs the fork's only asset. |
| One `LiveNode` per process | `TenantHost` single-runtime multi-tenancy | After PyO3 bindings exist for `TenantHost` **and** `tenant_id` is plumbed through the Python Redis configs. Revisit when idle-tenant hosting cost is measurable. |
| `data.binance.vision` | Tardis.dev | When you need L2/L3 book reconstruction, a second venue, or normalized cross-venue replay. Nautilus's Tardis adapter makes the switch an ingestion script. |
| `ParquetDataCatalog` (S3) | TimescaleDB | When a *UI* query over ledger time series is measurably slow. Never for backtest input. |
| pg-boss | BullMQ | Non-fund-affecting fan-out at volumes pg-boss cannot serve. Not v1. |
| Zod → JSON Schema → Pydantic | Protobuf | If a contract ever needs to cross into Rust *and* wire size matters. Neither is true. |
| Own LangGraph committee | TradingAgents fork | If the goal were a research demo rather than a product with a frozen output contract. |
| AWS KMS | Vault | Multi-cloud requirement, or a compliance mandate for on-prem key custody. |
| Redis msgbus seam | Postgres `LISTEN/NOTIFY` | If you drop Redis entirely — but Nautilus's cache backing already wants it. |

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `nautilus-trader 2.0.0rc4` | Python `>=3.12,<3.15` | `python/pyproject.toml`. Recommend 3.13. |
| `nautilus-trader 2.0.0rc4` | `maturin==1.15.0` **exact**, `uv >=0.12,<0.13`, Rust `1.98.0` | All three pinned in-repo. Floating any of them breaks the build. |
| `nautilus-trader` v1 | `nautilus-trader` v2 | **INCOMPATIBLE — same import name.** Separate venvs, never both. |
| `langgraph 1.2.11` | `langchain-core 1.6.2` | TradingAgents pins `langchain-core>=0.3.81` — a different generation. Do not mix. |
| `zod 4.5.4` | `@hono/zod-openapi 1.6.3` | zod-openapi 1.x targets Zod 4. `z.toJSONSchema()` requires Zod ≥4.0. |
| `prisma 7.8.x` | `@prisma/adapter-pg 7.8.x`, `pg 8.16` | Keep client and CLI on the same minor. Do **not** take `8.0.0-rc`. |
| `pg-boss 12.x` | PostgreSQL ≥13, `pg 8.x` | Creates its own schema; give it a dedicated one, not `public`. |
| Nautilus Redis backing | Redis ≥7 | `crates/infrastructure/src/redis/` checks server version at connect. |
| Binance spot SBE market data | Ed25519 keys **required** | `spot_market_data_mode=Json` is the credential-free path and is also required for real-time klines and `@ticker`. |

---

## Installation

```bash
# --- Engine (the fork; NOT from PyPI) ---
cd "/Users/criox4/Codes/Trade_Platform/Nautilus_Engine /nautilus_trader"
make build-debug        # root .venv + target/  (target/ currently 18 GB — provision disk)

# --- AI plane (new service) ---
uv init services/ai && cd services/ai
uv add langgraph langchain-core langchain-openai langchain-anthropic \
       pydantic polars duckdb pyarrow numpy scipy msgspec
uv add --dev pytest ruff datamodel-code-generator

# --- Control plane (existing apps/server) ---
pnpm --filter @repo/api add pg-boss @aws-sdk/client-kms
pnpm --filter @repo/api up hono@4 zod@4 @hono/zod-openapi@1 better-auth@1
# do NOT: pnpm up prisma@8  (RC)

# --- Contract codegen (run in CI, commit the output) ---
pnpm --filter @repo/contracts exec tsx scripts/emit-jsonschema.ts   # z.toJSONSchema()
uvx datamodel-code-generator --input contracts/jsonschema \
    --input-file-type jsonschema --output services/ai/contracts \
    --output-model-type pydantic_v2.BaseModel
```

---

## Flags for the roadmap

1. **The tenancy patch is not Python-reachable.** No PyO3 bindings; Python Redis configs hard-code `tenant_id: None`. The multi-tenant-single-runtime Key Decision cannot be validated from the Python control path today. Verification phase must test this in Rust, or the roadmap must accept process-per-tenant for v1. *(Highest-severity finding.)*
2. **Nautilus v2 is an RC.** `2.0.0rc4`, 2026-09-02. Pin a commit. Every phase touching the engine should budget for upstream API churn — the ROADMAP's stated priority #1 is literally "refine the Python bindings … close remaining API gaps."
3. **Nautilus explicitly scopes out** UI, distributed backtest orchestration, hyper-parameter optimization, and external database/monitoring integrations (`ROADMAP.md` "Out of scope"). Everything in Layers 3 and 6 of Quant-Phase is yours.
4. **v2 config objects are PyO3 `@final` types.** `python/tests/strategies/ema_cross.py:43-60` needs `__new__` gymnastics just to subclass `StrategyConfig`. The `DslStrategy` adapter will hit this. Budget for it; do not fight it.
5. **v2 ships an event store** (`crates/event_store/`, `docs/concepts/event_sourcing.md`) — an append-only, replayable, hash-chained log of every state-affecting message, with `redb` and memory backends. This substantially overlaps the "append-only audit store" requirement. Docs warn "the API surface is still evolving." Evaluate before building one; the audit store may be a projection of it rather than a new system.
6. **Historical data ingestion is unbuilt and unavoidable** — no in-tree Binance Vision loader. This is the Layer-0 phase.
7. **Ed25519 PEM secrets** change the credential schema and KMS envelope shape. Decide before the credential-storage phase, not after.

---

## Sources

**Local checkout — `/Users/criox4/Codes/Trade_Platform/Nautilus_Engine /nautilus_trader` @ `be9eaff8a7`** (confidence: HIGH — primary source)
- `version.json`, `python/pyproject.toml`, `rust-toolchain.toml`, `Cargo.toml` — versions and pins
- `MIGRATION_V2.md` — v1→v2 API surface, adapter parity caveats, out-of-tree adapter gap (issue 4694)
- `python/nautilus_trader/live/__init__.pyi` — `LiveNode`, `LiveNodeBuilder`, `LiveExecutionEngineConfig` reconciliation surface
- `python/nautilus_trader/common/__init__.pyi` — `CacheConfig`, `MessageBusConfig.external_streams`
- `python/nautilus_trader/infrastructure/__init__.pyi` — Redis/Postgres cache + msgbus backends
- `python/nautilus_trader/persistence/__init__.pyi` — `ParquetDataCatalog`, wranglers
- `python/nautilus_trader/adapters/binance/__init__.pyi`, `crates/adapters/binance/` (~140k LoC), `docs/integrations/binance.md` — order types, TIF, key types, environments, market-data modes
- `docs/concepts/reconciliation.md`, `docs/concepts/event_sourcing.md`, `crates/event_store/`
- `examples/live/binance/exec_tester.py` — canonical live wiring
- `git show 768cbf3664` (+ `--stat`), `crates/common/src/tenant.rs`, `crates/live/src/tenant.rs` — tenancy patch scope and its PyO3 gap
- `ROADMAP.md` — upstream in/out of scope

**Monorepo — `/Users/criox4/Codes/Trade_Platform/quant-platform`** (confidence: HIGH)
- `package.json`, `apps/server/package.json`, `apps/web/package.json`, `packages/fastapi-server/pyproject.toml` — pinned versions
- `.planning/PROJECT.md`, `docs/Architecture_Plan.md` §§15–18, `docs/Quant-Phase.md`

**Registries, queried 2026-09-05** (confidence: HIGH)
- PyPI JSON API — `nautilus_trader` (1.231.0 stable, 2.0.0rc4 2026-09-02), `langgraph` 1.2.11, `langchain-core` 1.6.2, `pydantic` 2.13.5, `polars` 1.44.1, `duckdb` 1.5.5, `datamodel-code-generator` 0.76.2, `tradingagents` 0.7.0 → **Mai0313 fork, not TauricResearch**
- npm registry — `pg-boss` 12.30.0, `bullmq` 6.3.4, `hono` 4.13.7, `zod` 4.5.4, `@hono/zod-openapi` 1.6.3, `prisma` 8.0.0-rc.13, `better-auth` 1.7.2, `next` 16.3.4
- GitHub API — `TauricResearch/TradingAgents`: 102,587 stars, Apache-2.0, `v0.4.0` 2026-08-31, pushed 2026-09-01, 362 open issues; `pyproject.toml` from `main`
- `s3-ap-northeast-1.amazonaws.com/data.binance.vision` — live listing; klines + aggTrades from 2017-08 with `.CHECKSUM`; delisted `SALTBTC`/`BCCBTC`/`MITHUSDT`/`TCTUSDT` present

**Web** (confidence: MEDIUM — corroborating only, superseded by the above where they conflict)
- [pg-boss vs BullMQ vs Bee-Queue 2026 — PkgPulse](https://www.pkgpulse.com/guides/bullmq-vs-bee-queue-vs-pg-boss-job-queues-nodejs-2026) — transactional-outbox support is pg-boss-only
- [ClickHouse vs TimescaleDB — Tinybird](https://www.tinybird.co/blog/clickhouse-vs-timescaledb), [OneUptime](https://oneuptime.com/blog/post/2026-01-21-clickhouse-vs-timescaledb/view)
- [Data Sourcing Guide — Quant Arb](https://www.algos.org/p/data-sourcing-the-guide), [Tardis.dev docs](https://docs.tardis.dev/faq/data)
- [esvhd/pypbo](https://github.com/esvhd/pypbo), [oxidecomputer/typify](https://github.com/oxidecomputer/typify), [quicktype](https://quicktype.io/)
- [TauricResearch/TradingAgents](https://github.com/tauricresearch/tradingagents)

---
*Stack research for: AI-first crypto quant platform on a forked NautilusTrader v2*
*Researched: 2026-09-05*
