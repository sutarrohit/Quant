# NautilusTrader Service — Implementation Spec

**Audience:** Claude Code (or any coding agent) building this service.
**Status of repo:** A FastAPI project already exists, created with `uv`. Extend it; do not scaffold a new project.

**Part II (bottom of this file) is the step-by-step implementation plan.** Part I below is the contract; Part II is the sequence. Where they disagree, Part I wins.

---

## 0. Read this first

NautilusTrader is a **library**, not a server. There is no daemon to install. We are building a thin Python service around it.

Two distinct runtimes come out of this, and they must not be merged into one process:

| | Backtest runtime | Live runtime |
|---|---|---|
| Nautilus entrypoint | `BacktestNode` | `TradingNode` |
| Process lifetime | seconds–minutes, then exits | days, supervised |
| Triggered by | HTTP job submission | desired-state row / operator action |
| Concurrency | N worker processes | one process per account |
| CPU | blocking, heavy | event loop, must never block |

**Build the backtest runtime first. The live runtime is Phase 5 and is explicitly out of scope until Phases 0–4 pass their acceptance tests.**

### The single most important rule

Strategies are **never generated as Python source code**. There is exactly one strategy class, `DslStrategy`, which receives the strategy spec as a plain dict in its config and interprets it at runtime.

Reasons, in priority order:

1. No `exec()`/`eval()` of user or LLM-authored code in a process that will later hold exchange credentials.
2. The identical class runs in backtest and live, so simulation and production cannot drift.
3. Strategy specs become data — versionable, hashable, diffable, storable in Postgres.

If you find yourself writing a code generator that emits `.py` files, stop: that is the wrong branch.

---

## 1. Non-goals for this spec

Do not build these. They belong to other services or later phases:

- Order execution against a real exchange.
- Credential storage, KMS, decryption.
- Risk kernel, mandates, approvals (these live in the TypeScript `trading-core`).
- LLM calls, research agents, strategy authoring from natural language.
- Authentication beyond a shared internal secret.
- A UI of any kind.

This service does exactly three things: **hold market data, run backtests, and (later) run live strategies that emit intents.**

---

## 2. Dependencies

Pin versions. Nautilus's Python API changes between minor releases, and this spec was written against a specific API shape.

```bash
uv add "nautilus_trader"        # then pin the resolved version in pyproject.toml
uv add pydantic pydantic-settings
uv add "arq"                     # job queue; redis-backed, asyncio-native
uv add redis                     # cache-db + message-bus backing (Phase 5+)
uv add pandas pyarrow
uv add --dev pytest pytest-asyncio hypothesis ruff mypy
```

**No SQLAlchemy, no Alembic, no asyncpg.** This service owns no relational schema of its own — see §9. If you find yourself wanting migrations here, re-read that section first; the answer is almost certainly that the data belongs to `api-control`.

**First task before writing any code:** run `uv run python -c "import nautilus_trader; print(nautilus_trader.__version__)"`, then open the docs for that exact version at `https://nautilustrader.io/docs/`. Confirm the import paths below still exist. Where this spec and the installed version disagree, **the installed version wins** — and note the deviation in `docs/nautilus-api-notes.md`.

Import paths this spec assumes:

```python
from nautilus_trader.backtest.node import BacktestNode, BacktestRunConfig
from nautilus_trader.backtest.node import BacktestDataConfig, BacktestVenueConfig, BacktestEngineConfig
from nautilus_trader.config import ImportableStrategyConfig, StrategyConfig, LoggingConfig
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model import Bar, BarType, InstrumentId, Quantity, Price
```

---

## 3. Target layout

Add to the existing project:

```
src/<pkg>/
  api/
    __init__.py
    app.py                  # FastAPI app factory (may already exist)
    routes/
      health.py
      backtests.py
      catalog.py
    deps.py                 # DI: settings, redis, db session
  dsl/
    schema.py               # Pydantic models for the strategy spec
    validator.py            # semantic validation beyond schema
    interpreter.py          # condition evaluation
    indicators.py           # spec indicator name -> Nautilus indicator factory
  strategies/
    dsl_strategy.py         # the ONE strategy class
  backtest/
    builder.py              # spec + request -> BacktestRunConfig
    runner.py               # executes BacktestNode, extracts results
    results.py              # result extraction / metrics
  data/
    catalog.py              # ParquetDataCatalog access
    ingest.py               # exchange OHLCV -> Bar -> catalog
    quality.py              # gap / outlier / duplicate checks
  worker/
    main.py                 # arq worker entrypoint
    tasks.py                # run_backtest task
  store/
    jobs.py                 # job records in Redis (status, idempotency)
    artifacts.py            # equity curve / trade table -> parquet on disk or S3
  live/                     # Phase 5+, do not create earlier
    node.py                 # TradingNode assembly + CacheConfig/MessageBusConfig
    exec_client.py          # Option A: emits TradeIntent instead of hitting a venue
    bridge.py               # message-bus <-> trading-core transport
    recovery.py             # startup reconciliation before subscribing
  settings.py
tests/
  dsl/
  backtest/
  data/
  fixtures/
docs/
  nautilus-api-notes.md
```

Config via `pydantic-settings`, env-prefixed `NT_`.

| Setting | Phase | Purpose |
|---|---|---|
| `NT_CATALOG_PATH` | 0 | Parquet catalog root (local path or `s3://...`) |
| `NT_ARTIFACT_PATH` | 3 | Where result parquet/JSON is written |
| `NT_REDIS_URL` | 3 | arq job queue |
| `NT_INTERNAL_API_KEY` | 3 | Shared bearer token for `api-control` |
| `NT_LOG_LEVEL` | 0 | — |
| `NT_CACHE_REDIS_URL` | 5 | Nautilus cache database (separate DB index from arq) |
| `NT_BUS_REDIS_URL` | 6 | Nautilus message bus backing |
| `NT_TRADING_CORE_URL` | 6 | Where `TradeIntent` is delivered |

There is deliberately no `NT_DATABASE_URL`.

---

## 4. Phase 0 — Data catalog

**Nothing else can be tested until this works.** `BacktestNode` reads from a `ParquetDataCatalog`, not from CSVs and not from Postgres.

### 4.1 Ingestion

Write `data/ingest.py` with a CLI entrypoint:

```bash
uv run python -m <pkg>.data.ingest \
  --exchange binance --symbol BTCUSDT --market spot \
  --timeframe 15m --start 2023-01-01 --end 2025-01-01
```

Steps:

1. Fetch OHLCV from the exchange public REST API in paged windows, respecting rate limits. Retry with backoff on 429/5xx.
2. Persist the **raw** response to object storage or a local `raw/` directory before transformation. Raw data is the audit trail; never overwrite it.
3. Build the Nautilus `Instrument` for the symbol (use `TestInstrumentProvider` only in tests; in ingestion, construct the real instrument from exchange metadata: price precision, size precision, min notional, tick size, lot size).
4. Convert rows to Nautilus `Bar` objects with correct `BarType` and nanosecond timestamps.
5. `catalog.write_data(instruments)` and `catalog.write_data(bars)`.

### 4.2 Timestamp discipline

This is where backtests silently become wrong. Enforce:

- All timestamps UTC, nanoseconds, integer.
- `ts_event` = **bar close** time, not bar open. Exchange APIs usually return open time; you must add the interval.
- `ts_init` = the time the platform could first have known the bar = `ts_event` for historical ingest.
- Never allow `ts_init < ts_event`.

Write an assertion in ingestion that fails loudly on violation.

### 4.3 Quality monitors

`data/quality.py`, run automatically after every ingest, results written to Postgres:

- Gap detection: any missing interval in the expected bar sequence.
- Duplicate `ts_event` detection.
- Outlier flag: bar range > N× trailing median range.
- Zero-volume / zero-range bar counts.
- Monotonicity: timestamps strictly increasing.

Ingestion **fails** on duplicates or non-monotonic timestamps. It **warns** on gaps and outliers.

### 4.4 Acceptance test for Phase 0

- `uv run pytest tests/data` green.
- Two years of 15m BTC/USDT bars in the catalog.
- `catalog.bars(...)` returns them in order with correct close-aligned timestamps.
- A deliberately corrupted fixture (duplicate row, out-of-order row, missing day) is caught by `quality.py`.

---

## 5. Phase 1 — DSL schema and interpreter

### 5.1 Schema (`dsl/schema.py`)

Pydantic v2 models, `frozen=True`, `extra="forbid"`. The `extra="forbid"` is not optional — a typo in a spec field must be a hard error, never a silently ignored rule.

Model this shape:

```json
{
  "strategyId": "btc-rsi-recovery",
  "version": 4,
  "market": {
    "exchange": "binance",
    "marketType": "spot",
    "symbols": ["BTC/USDT"],
    "timeframe": "15m"
  },
  "entry": {
    "all": [
      { "indicator": "rsi", "period": 14, "operator": "crossesAbove", "value": 30 },
      { "indicator": "volume", "operator": "greaterThanSma", "period": 20 }
    ]
  },
  "exit": {
    "any": [
      { "type": "takeProfitPercent", "value": 4 },
      { "type": "stopLossPercent", "value": 2 },
      { "indicator": "rsi", "period": 14, "operator": "greaterThan", "value": 70 }
    ]
  },
  "sizing": { "type": "riskPercent", "riskPercent": 1 }
}
```

Rules:

- Condition groups are recursive: `{"all": [...]}` / `{"any": [...]}` / `{"not": {...}}`, leaves are conditions. Cap nesting depth at 5 and total leaf count at 32. Reject deeper specs — this bounds interpreter cost and stops pathological LLM output.
- Use a discriminated union for leaves: indicator conditions (discriminated on `indicator`) and exit conditions (discriminated on `type`).
- All numeric values that touch money or price are `Decimal`, parsed from strings. Never `float` for prices, quantities, or notionals. Indicator parameters (periods, thresholds like RSI 30) may be `int`/`float`.
- `timeframe` is a closed enum: `1m 5m 15m 1h 4h 1d`. Add more later, deliberately.

### 5.2 Semantic validator (`dsl/validator.py`)

Schema validity is not enough. Reject with a structured error list:

- Indicator/operator combination unsupported (e.g. `crossesAbove` on a non-series value).
- Indicator period larger than available warmup for the requested backtest window.
- `entry` group empty, or `exit` group empty.
- `stopLossPercent` missing when the caller requires stops.
- Symbol not present in the catalog.
- Same indicator declared twice with conflicting parameters.

Error format:

```python
class SpecError(BaseModel):
    path: str        # "entry.all[1].period"
    code: str        # "INDICATOR_PERIOD_TOO_LARGE"
    message: str
    limit: str | None = None
    observed: str | None = None
```

### 5.3 Interpreter (`dsl/interpreter.py`)

A pure function over a snapshot of indicator values and bar state:

```python
def evaluate(node: ConditionNode, ctx: EvalContext) -> bool: ...
```

`EvalContext` carries: current bar, previous bar, resolved indicator values (current and previous, so `crossesAbove` is expressible), position state, entry price, unrealised PnL percent.

Hard requirements:

- **Pure and side-effect free.** No I/O, no clock reads, no logging of mutable state. It must be unit-testable without Nautilus.
- **No lookahead.** The context is constructed only from data at or before the current bar's close. Any access to a future bar is a bug; add a test that would catch it.
- `crossesAbove` = previous value ≤ threshold **and** current value > threshold. Define `crossesBelow` symmetrically. Return `False` when the previous value is unavailable (warmup) rather than guessing.
- Unknown indicator or operator raises, never returns `False`. Silent falsity hides broken strategies.

### 5.4 Indicator registry (`dsl/indicators.py`)

A single dict mapping DSL indicator names to a factory returning a Nautilus indicator instance plus a value accessor.

```python
INDICATORS: dict[str, IndicatorSpec] = {
    "rsi": IndicatorSpec(factory=lambda p: RelativeStrengthIndex(p["period"]), value=lambda i: i.value),
    "sma": ...,
    "ema": ...,
    "atr": ...,
    "volume": ...,   # from the bar, not an indicator object
}
```

Adding an indicator must mean adding one entry here and one test. If it requires touching the interpreter, the abstraction is wrong.

### 5.5 Acceptance test for Phase 1

- Property test: any spec that passes schema + validator can be evaluated without raising on a synthetic bar series.
- Table-driven tests for each operator, including warmup boundaries and exact-equality edges.
- A spec with an unknown indicator is rejected at validation, not at runtime.
- Round-trip: spec → JSON → spec is byte-identical, and its SHA-256 is stable across processes (needed later for `strategyVersionId` hashing).

---

## 6. Phase 2 — `DslStrategy`

`strategies/dsl_strategy.py`. One class. It is imported by Nautilus via `ImportableStrategyConfig`.

```python
class DslStrategyConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    spec: dict                    # validated upstream; the raw spec dict
    strategy_version_id: str
    spec_hash: str


class DslStrategy(Strategy):
    def on_start(self) -> None:
        # 1. resolve instrument from cache; abort if missing
        # 2. build indicators from spec via INDICATORS registry
        # 3. register each indicator for bars
        # 4. subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        # 1. return early until every indicator .initialized
        # 2. build EvalContext (current + previous values, position state)
        # 3. flat  -> evaluate spec["entry"]  -> submit entry if true
        #    in position -> evaluate spec["exit"] -> close if true
```

Requirements:

- **Sizing** comes from `spec["sizing"]`. For `riskPercent`, quantity = (account equity × riskPercent) / (entry price × stopLossPercent) — then round **down** to the instrument's size precision and reject if below min notional. Never round up into a larger position than the risk budget allows.
- **Bar-close semantics only** in v1. Signals evaluate on closed bars; entries are submitted for the next bar. Document this explicitly in the strategy docstring — intrabar fills are a deliberate later decision, not an accident.
- **No network calls, no file reads, no `datetime.now()`** inside the strategy. Use `self.clock`.
- Log every signal decision with `strategy_version_id`, `spec_hash`, bar timestamp, and the evaluated condition results. This log is what later explains "why did the agent trade."
- One position at a time per instrument in v1. Reject specs implying pyramiding.

### Acceptance test for Phase 2

- The strategy runs end-to-end in a `BacktestNode` on catalog data and produces at least one round-trip trade.
- Determinism: the same spec + same data + same seed produces byte-identical fills across three runs. Assert this in CI.
- A spec that never triggers produces zero orders and does not raise.

---

## 7. Phase 3 — Backtest job service

### 7.1 Why a queue

A backtest takes minutes and pins a CPU. Running it inside a FastAPI request handler will block the event loop and time out the caller. **The HTTP handler must only enqueue.**

### 7.2 API contract

The TypeScript `api-control` service is the only caller. Authenticate with a static bearer token from `NT_INTERNAL_API_KEY`, checked in a dependency.

```
POST /v1/backtests
```

Request:

```json
{
  "requestId": "req_01K...",
  "strategyVersionId": "sv_01K...",
  "spec": { ...DSL... },
  "venue": "BINANCE",
  "instrumentId": "BTCUSDT.BINANCE",
  "barType": "BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL",
  "start": "2023-01-01T00:00:00Z",
  "end": "2025-01-01T00:00:00Z",
  "startingBalances": ["10000 USDT"],
  "fees": { "makerBps": "1", "takerBps": "10" },
  "slippageBps": "5"
}
```

`requestId` is the **idempotency key**. A repeat submission with the same `requestId` returns the existing job, never a second run.

Responses:

- `202` → `{"jobId": "...", "status": "QUEUED"}`
- `422` → `{"errors": [SpecError, ...]}` — validation runs synchronously, before enqueue, so callers get fast feedback on bad specs.
- `409` → duplicate `requestId` with a *different* payload.

```
GET /v1/backtests/{jobId}
```

→ `{"jobId","status","submittedAt","startedAt","finishedAt","error","result"}` where `status ∈ QUEUED|RUNNING|SUCCEEDED|FAILED|CANCELLED`.

```
DELETE /v1/backtests/{jobId}     # cancel if not yet running
GET    /v1/catalog/instruments   # what can actually be backtested
GET    /health  /ready
```

Optionally POST a webhook to a caller-supplied URL on completion. Poll-first is fine for v1.

### 7.3 Builder (`backtest/builder.py`)

Pure function: `(request, spec) -> BacktestRunConfig`. No side effects, so it is unit-testable.

```python
venue = BacktestVenueConfig(
    name=req.venue,
    oms_type="NETTING",
    account_type="CASH",
    base_currency=None,
    starting_balances=req.starting_balances,
)
data = BacktestDataConfig(
    catalog_path=settings.catalog_path,
    data_cls=Bar,
    instrument_id=req.instrument_id,
    bar_types=[req.bar_type],
    start_time=req.start,
    end_time=req.end,
)
engine = BacktestEngineConfig(
    strategies=[ImportableStrategyConfig(
        strategy_path="<pkg>.strategies.dsl_strategy:DslStrategy",
        config_path="<pkg>.strategies.dsl_strategy:DslStrategyConfig",
        config={
            "instrument_id": req.instrument_id,
            "bar_type": req.bar_type,
            "spec": spec.model_dump(mode="json"),
            "strategy_version_id": req.strategy_version_id,
            "spec_hash": spec_hash(spec),
        },
    )],
    logging=LoggingConfig(log_level=settings.log_level),
)
return BacktestRunConfig(engine=engine, venues=[venue], data=[data])
```

**Fees and slippage are mandatory inputs, never defaulted to zero.** A zero-cost backtest is a marketing number, not a result. If the caller omits them, reject with `422`.

### 7.4 Runner (`backtest/runner.py`)

Runs in the arq worker, not the API process.

- Instantiate `BacktestNode(configs=[cfg])`, call `.run()`.
- Retrieve the engine by run-config ID to pull reports (`generate_order_fills_report()`, `generate_positions_report()`, account report).
- Enforce a wall-clock timeout; kill and mark `FAILED` with `code: "TIMEOUT"`.
- Catch exceptions, persist the traceback to the job row, never leak it in the HTTP response beyond a code and a short message.
- Explicitly `dispose()` / drop the engine after extraction. Nautilus engines hold a lot of memory; a leaking worker will OOM after a few dozen jobs. Consider `max_jobs` per worker process with recycling.

### 7.5 Results (`backtest/results.py`)

Persist to Postgres (summary) and object storage / parquet (series):

Summary metrics: total return, CAGR, max drawdown, Sharpe, Sortino, win rate, profit factor, trade count, average and median trade, average holding period, total fees paid, **total slippage cost**, exposure percent.

Series artifacts: equity curve, drawdown curve, per-trade table (entry/exit time, price, quantity, fees, slippage, PnL, and the triggering condition).

Return in the API response a summary object plus URLs/IDs for the series artifacts. Do not inline a 50k-row equity curve in JSON.

### 7.6 Acceptance test for Phase 3

- Submit → poll → `SUCCEEDED` with a summary, against real catalog data, in an integration test.
- Duplicate `requestId` returns the same `jobId` and does not double-run.
- Invalid spec returns `422` in under 100 ms without touching the queue.
- Worker survives 50 sequential jobs without unbounded memory growth (assert RSS ceiling).

---

## 8. Phase 4 — The milestone that actually matters

**Reproduce a published backtest within tolerance.**

Pick a strategy with published, reproducible results (a documented Nautilus example, or a well-specified public strategy with stated data, fees, and period). Express it in the DSL. Run it through this service. Compare.

If the numbers don't land within tolerance, **stop and fix the data or the simulator**. Do not build Phase 5. Every downstream number is meaningless until this passes.

Record the comparison in `docs/reproduction-<name>.md`: source, data used, fee assumptions, expected metrics, achieved metrics, delta, and the explanation for any delta.

---

## 9. Storage architecture — what stores what

Nautilus has three distinct storage roles. They are frequently confused with each other and with the platform's own database. Keep them separate.

| Store | Technology | Backtest (0–4) | Live (5–6) | Owned by |
|---|---|---|---|---|
| Historical market data | `ParquetDataCatalog` (files) | **Required** | Required | this service |
| Nautilus cache database | Redis | **Not used** | **Required** | this service |
| Nautilus message bus backing | Redis | Not used | Required for Option A | this service |
| Job status / idempotency | Redis (arq) | Required | Required | this service |
| Result artifacts | Parquet / object storage | Required | — | this service |
| Ledger, orders, fills, audit, mandates | PostgreSQL | — | — | **`api-control` / `trading-core` (TypeScript)** |

### 9.1 Parquet data catalog

Files, not a server. Local disk or S3/GCS via fsspec. Holds bars, ticks, book deltas, instrument definitions. `BacktestNode` reads from it directly. Covered in Phase 0.

### 9.2 Nautilus cache database (Redis)

The Nautilus `Cache` is an in-memory store of orders, positions, accounts and recent market data. Without a configured backend it is lost on process exit.

```python
from nautilus_trader.config import CacheConfig, DatabaseConfig

cache = CacheConfig(
    database=DatabaseConfig(
        type="redis",
        host=settings.cache_redis_host,
        port=settings.cache_redis_port,
        timeout=2,
    ),
    encoding="msgpack",       # or "json" while debugging
    timestamps_as_iso8601=True,
    flush_on_start=False,     # NEVER True in live — it wipes recovered state
)
```

Rules:

- **Do not configure this in backtests.** It adds write latency to every event for zero benefit, and it breaks the determinism test in §10 because two runs then share mutable external state. Backtest = in-memory cache only.
- **Required in live.** Without it, a restart loses open orders and position state, and startup recovery has nothing to compare the venue against.
- Use a **separate Redis logical DB (or instance) from arq.** A `FLUSHDB` aimed at the job queue must never be able to erase live trading state.
- `flush_on_start=False` in every live config. Add a test that asserts this.
- A PostgreSQL backend for the cache also exists, but it is newer and less exercised than Redis. Use Redis. Revisit only if there's a concrete reason, and record it in an ADR.
- The cache is **not** the ledger. Nautilus's own docs are explicit that it isn't a full database replacement. It is crash-recovery state with a short retention horizon. The durable financial record stays in the TypeScript Postgres.

### 9.3 Message bus backing (Redis)

Nautilus can back its internal message bus with Redis, publishing events to streams that other processes can consume. This is how the Python live node talks to the outside world without either side importing the other.

```python
from nautilus_trader.config import MessageBusConfig, DatabaseConfig

bus = MessageBusConfig(
    database=DatabaseConfig(type="redis", host=..., port=...),
    encoding="msgpack",
    timestamps_as_iso8601=True,
    streams_prefix="nt",
    use_trader_prefix=True,
    autotrim_mins=60,          # bound stream growth
    types_filter=[],           # publish everything; narrow later if volume demands
)
```

Rules:

- Backtest: not used.
- Live Option A: required — this is the transport carrying `TradeIntent` out and fill events back in.
- Live Option B: optional, useful for observability only.
- Set `autotrim_mins`. An untrimmed Redis stream will fill the instance and take the node down with it.
- The bus is a **transport, not a store of record.** Anything that must survive is written by `trading-core` to Postgres on receipt. Never treat "it's in the stream" as "it's recorded."

### 9.4 PostgreSQL — not ours

`api-control` and `trading-core` own Postgres: users, accounts, mandates, strategy versions, trade intents, risk decisions, approvals, orders, fills, positions, outbox, audit. This Python service **never connects to it**, in any phase.

Why the hard line: two services writing the same financial tables is how you get an order recorded twice, or a fill that exists in one schema and not the other. The Python side proposes; the TypeScript side records. One writer per table.

Backtest results are the one grey area — they're the Python service's output but the TypeScript side wants to query them. Resolve it by POSTing the summary to `api-control` on job completion and letting it own that table. Don't reach into the database.

---

## 10. Phase 5 — Live runtime (`TradingNode`)

Do not start until Phases 0–4 are green and ADR-001 (below) is written.

Nautilus's `TradingNode` ships its **own** OMS, execution clients, and venue adapters. If we let it trade Binance directly, it holds the API credentials and our TypeScript risk kernel and OMS are bypassed. That contradicts the platform rule that the risk kernel is the sole authorization authority.

Two options, decide before writing live code:

**Option A — Nautilus proposes, TypeScript executes.**
Implement a custom execution client that, instead of hitting an exchange, emits a `TradeIntent` to the TypeScript `trading-core` (via outbox/queue) and waits for fill events to be pushed back in. Risk kernel stays authoritative; credentials never enter Python. Cost: the execution layer differs between backtest and live, so the "same code path" guarantee covers strategy logic but not fills.

**Option B — Nautilus executes, risk runs inside it.**
Port the risk checks into a Nautilus `Actor` / execution algorithm that vetoes orders pre-submission. Preserves the shared code path all the way to fills. Cost: credentials live in the Python process, and the risk rules exist in two languages or must be moved wholesale to Python.

Recommendation: **Option A**, because credential isolation and a single authoritative risk kernel are harder to retrofit than execution parity. But make the decision explicitly and write it into `docs/adr-001-live-execution.md` before any code in `live/`.

### 10.1 Process model

One `TradingNode` process per exchange account. Not per strategy, not one shared node — an account is the unit of risk, credentials, and reconciliation, so it is the unit of process isolation.

Each process is supervised (systemd, k8s Deployment, whatever) and restarts automatically. It is started/stopped by reading a desired-state record from `api-control`, never by an HTTP call that runs the node inside the API process.

### 10.2 Node assembly (`live/node.py`)

```python
config = TradingNodeConfig(
    trader_id=TraderId(f"NT-{account_id}"),
    cache=CacheConfig(database=DatabaseConfig(type="redis", ...), flush_on_start=False),
    message_bus=MessageBusConfig(database=DatabaseConfig(type="redis", ...), autotrim_mins=60),
    data_clients={...},
    exec_clients={...},        # Option A: our TradeIntent client
    strategies=[ImportableStrategyConfig(... same DslStrategy ...)],
)
```

The `ImportableStrategyConfig` here must be **byte-identical in shape** to the one the backtest builder produces. Same `strategy_path`, same `spec`, same `spec_hash`. Extract that construction into one shared function used by both `backtest/builder.py` and `live/node.py`. If the two ever diverge, the platform's core guarantee is gone.

### 10.3 Startup recovery (`live/recovery.py`)

On every start, in this order, **before subscribing to any data or starting any strategy**:

1. Load cache state from Redis.
2. Fetch open orders, recent fills, balances and positions from the venue.
3. Compare. Any discrepancy → do not start; emit an alert and stay in a halted state.
4. Only on a clean match, start strategies.

A node that starts trading on stale or unverified state is worse than a node that stays down.

### 10.4 Acceptance test for Phase 5

- Kill -9 the node mid-position, restart, and confirm it recovers the open position from Redis and matches it against a stubbed venue.
- `flush_on_start=True` anywhere in a live config fails a test.
- Cache Redis and arq Redis are provably separate (different DB index or instance) — asserted in config validation.
- A backtest run with a cache database configured fails fast with a clear error.

---

## 11. Phase 6 — Intent bridge (Option A only) — **NOT BEING BUILT**

> **ADR-001 chose Option B, and this section is dead.** Nautilus's `TradingNode`
> submits orders to the venue directly; nothing else sends a live trade. The ADR
> states that "spec §11 describes roughly a phase of work that this decision
> deletes", and it does.
>
> The whole of it goes: the `TradeIntent` schema, the execution client that
> published instead of trading, idempotent inbound fill consumption, and the
> bounded-wait-then-pause protocol. Every one was a place for two systems to
> disagree about what happened.
>
> **Kept, not deleted, so the decision stays legible.** This is what was
> considered and rejected. If a future step seems to need a `TradeIntent`, the
> question is whether Option B is still right — not whether to add the bridge
> back quietly. See §II.13's "Phase 6 — deleted by ADR-001" for what replaces
> it: one-way fill reporting to `api-control`, which is a step, not a phase.

If ADR-001 selects Option A, this is where the Python node stops being self-contained.

### 11.1 Outbound: `TradeIntent`

Implement a custom execution client (`live/exec_client.py`) that satisfies the Nautilus execution-client interface but, on order submission, publishes a `TradeIntent` to the message bus instead of calling a venue.

It must **not** invent platform-owned fields. `tenantId`, `accountId`, `mandateId`, `idempotencyKey`, `riskDecisionId`, `approvalId`, `clientOrderId` are all set by `trading-core`. The Python side supplies only: strategy version, signal reference, symbol, side, order type, quantity, price, and the evaluated conditions that triggered it.

### 11.2 Inbound: fill events

`trading-core` publishes order acknowledgements, fills, cancels and rejects back onto a stream the node consumes, which it translates into Nautilus `OrderFilled` / `OrderRejected` / `OrderCanceled` events so the strategy and cache stay consistent with reality.

Requirements:

- **Idempotent consumption.** Every inbound event carries an ID; replays are ignored, not double-applied. Redis streams redeliver on restart; this will happen.
- **Bounded wait.** If an intent gets no response within a timeout, the order goes to an `UNKNOWN`-equivalent state and the strategy is paused for that instrument. Never retry an intent blindly.
- **The bridge is not the record.** `trading-core` writes to Postgres on receipt; the stream is transport only.

### 11.3 Acceptance test for Phase 6

- Round trip: strategy signal → `TradeIntent` on stream → stubbed `trading-core` responds with a fill → Nautilus position updates correctly.
- Replaying the same fill event twice produces one position change.
- A dropped response leaves the order in the unresolved state and pauses the strategy, rather than resubmitting.

---

## 12. Cross-cutting requirements

**Determinism.** Same spec + same data + same config → identical results. No `random` without a seeded generator, no `datetime.now()`, no dict-ordering dependence, no set iteration in output paths. There is a CI test for this; do not weaken it.

**Decimals.** Prices, quantities, notionals, fees, balances: `Decimal` from strings, end to end. `float` appears only inside indicator math.

**Structured logging.** JSON logs with `job_id`, `strategy_version_id`, `spec_hash`, `request_id`. No spec contents at INFO (they get large); DEBUG only.

**Errors.** Every failure returns a stable machine-readable `code`. The TypeScript caller branches on codes, never on message text.

**Typing.** `mypy --strict` on `dsl/`, `strategies/`, `backtest/`. These are the modules where a type error becomes a wrong number.

**Tests.** Unit tests for the interpreter and validator. Integration tests for ingest → catalog → backtest → result. Golden-file tests for backtest output on a small fixed dataset — a diff in the golden file means behaviour changed, and that must be a deliberate act.

---

## 13. Pitfalls — read before starting each phase

1. **Running a backtest inside the HTTP handler.** Blocks the loop, times out, kills the service under two concurrent users.
2. **Bar open vs bar close timestamps.** The most common source of a backtest that looks great and fails live.
3. **Zero fees, zero slippage.** Produces the fantasy numbers this platform exists to refute.
4. **Reusing one `BacktestEngine` across jobs.** State leaks between runs. Fresh engine per job, always.
5. **Generating Python from the DSL.** Discussed above; it is the wrong branch.
6. **Survivorship bias in the universe.** Delisted symbols must exist in the catalog. Not urgent for single-symbol BTC v1, but do not build an ingestion API that makes it impossible later.
7. **`float` for money.** Silent, cumulative, and unrecoverable once it's in stored results.
8. **Assuming this spec's Nautilus API is current.** Check the installed version's docs first.
9. **Catching broad exceptions in the interpreter and returning `False`.** Turns a broken strategy into a silently inert one.
10. **Configuring a cache database in backtests.** Slows every event, and shared external state breaks the determinism guarantee.
11. **Sharing one Redis DB between arq and the Nautilus cache.** A queue flush then destroys live position state.
12. **`flush_on_start=True` in live.** Wipes exactly the state recovery depends on.
13. **Untrimmed message-bus streams.** Redis fills, node dies. Set `autotrim_mins`.
14. **Connecting this service to the platform Postgres.** Two writers on financial tables. Propose over the bus; let TypeScript record.
15. **Treating a message-bus stream as durable history.** It's transport. Durability is Postgres on the TypeScript side.

---

## 14. Build order and definition of done

| Phase | Deliverable | Storage added | Done when |
|---|---|---|---|
| 0 | Catalog + ingest + quality | Parquet catalog | 2y of 15m BTC bars in catalog; corrupted fixtures caught |
| 1 | DSL schema, validator, interpreter | — | Operator tests green; hash stable; bad specs rejected |
| 2 | `DslStrategy` | — | Runs in `BacktestNode`; three runs byte-identical |
| 3 | Job API + worker + results | Redis (arq), artifact store | Submit→poll→result integration test green; idempotent |
| 4 | Reproduction milestone | — | Published result matched within documented tolerance |
| 5 | `TradingNode` + recovery | Redis cache DB | Kill -9 recovers open position; separate Redis asserted |
| 6 | Intent bridge (Option A) | Redis message bus | Round trip green; duplicate fill applied once |

Work strictly in this order. Each phase's acceptance tests must be green and committed before the next begins. If a phase's tests can't be made green, that is a design problem to surface, not a step to skip.

---
---

# Part II — Implementation Plan

**Written:** 2026-09-04. **Owner:** Claude Code. **Reviewer:** repo owner.
Part I (§0–§14 above) is the *contract*. This part is the *sequence*. Where the two disagree, Part I wins.

## II.0 Working agreement

- **One step per session.** Each numbered step below is a single reviewable unit of work. Build it, make its tests green, stop, and wait for review before starting the next.
- **No commits.** Nothing is committed to git until the repo owner explicitly says so. (The directory is not currently a git repo — do not `git init` unprompted either.)
- **Each step ends with:** its own tests green, `ruff check .` clean, and `mypy` clean over the modules that step touched.
- **Acceptance tests are gates, not suggestions.** A phase's acceptance step must pass before the first step of the next phase begins (§14).
- **Deviations get recorded.** Any place the installed Nautilus API differs from Part I goes in `docs/nautilus-api-notes.md` with the version number, in the same step that discovered it.

## II.1 Environment facts (verified 2026-09-04, not assumed)

Resolved and imported in a throwaway venv before writing this plan:

| Fact | Value |
|---|---|
| Python | 3.13 (`3.13.15`); `nautilus_trader` resolves and installs cleanly |
| `nautilus_trader` | **1.231.0** — pin this exact version |
| `uv` | 0.12.9 |

Import paths from §2 **confirmed present** in 1.231.0:

`BacktestNode` · `BacktestRunConfig` · `BacktestDataConfig` · `BacktestVenueConfig` · `BacktestEngineConfig` (all re-exported from `nautilus_trader.backtest.node`, canonically in `nautilus_trader.backtest.config`) · `ImportableStrategyConfig` · `StrategyConfig` · `LoggingConfig` · `CacheConfig` · `DatabaseConfig` · `MessageBusConfig` · `TradingNodeConfig` · `ParquetDataCatalog` · `Strategy` · `Bar` · `BarType` · `InstrumentId` · `Quantity` · `Price` · `TradingNode`.

**One deviation found.** §5.4 implies per-indicator submodules (`nautilus_trader.indicators.rsi` etc.). Those do not exist. In 1.231.0 indicators are exported flat:

```python
from nautilus_trader.indicators import (
    RelativeStrengthIndex, SimpleMovingAverage, ExponentialMovingAverage, AverageTrueRange,
)
```

This goes into `docs/nautilus-api-notes.md` in Step 1.

## II.2 Naming and layout decisions

| Decision | Value | Rationale |
|---|---|---|
| Package | `engine`, at `src/engine/` | §3 says `src/<pkg>/`. Short, and `strategy_path` strings stay readable: `engine.strategies.dsl_strategy:DslStrategy`. |
| Distribution name | `engine-server` | Matches the directory. |
| Build backend | `uv_build`, `src/` layout | Makes `engine` importable by the arq worker and by Nautilus's `ImportableStrategyConfig` without path hacks. |
| Env prefix | `NT_` | §3. |
| Python | `>=3.13,<3.14` | Verified above. |

Everything at the repo root that is not config moves under `src/engine/`. No more root-level `main.py`, `config.py`, `auth.py`.

## II.3 Step ladder

Legend: **Gate** = the check the reviewer runs. Steps marked ★ are phase acceptance gates.

---

### Step 0 — Teardown

Strip the FastAPI blog template down to an empty, correctly-configured shell.

**Delete:** `auth.py` · `config.py` · `main.py` · `exceptions.py` · `db/` · `routers/` · `service/` · `schema/` · `scripts/` · `tests/` · `alembic/` · `alembic.ini` · `blog.db` · `media/` · `README.md` · `package.json` (vestigial: the template was authored for a pnpm monorepo that does not exist here — this is a pure Python project, `uv` is the only task runner).

**Rewrite:** `pyproject.toml` (name, `src/` layout, Nautilus dependency set per §2, ruff + mypy + pytest config) · `.env` / `.env.example` (`NT_*` only) · `.gitignore` (drop media/sqlite rules; add `catalog/`, `raw/`, `artifacts/`) · `.dockerignore` · `Dockerfile` · `docker-compose.yml` (placeholder until Step 17) · `README.md` (what this service is, per §0).

**Removed dependencies:** `sqlalchemy`, `alembic`, `aiosqlite`, `pwdlib`, `pyjwt` — §2 is explicit that this service owns no relational schema.

**Gate:** repo contains no blog code; `uv sync` succeeds; `uv run python -c "import nautilus_trader; print(nautilus_trader.__version__)"` prints `1.231.0`.

---

### Step 1 — Skeleton and cross-cutting foundations

Everything downstream depends on these, so they come before any domain code.

| File | Contents |
|---|---|
| `src/engine/settings.py` | `pydantic-settings`, `env_prefix="NT_"`. Phase-0/3 keys from §3 only (`CATALOG_PATH`, `ARTIFACT_PATH`, `RAW_PATH`, `REDIS_URL`, `INTERNAL_API_KEY`, `LOG_LEVEL`). Phase 5/6 keys are added in their own phase, not stubbed now. **No `NT_DATABASE_URL`, ever.** |
| `src/engine/logging.py` | JSON structured logging (§12). Context fields `job_id`, `strategy_version_id`, `spec_hash`, `request_id` bound via `contextvars`. Spec bodies at DEBUG only. |
| `src/engine/errors.py` | Replaces the template `exceptions.py`. Every error carries a stable machine-readable `code` (§12) — the TypeScript caller branches on codes, never message text. |
| `src/engine/api/app.py` | App factory. No CORS (the only caller is server-side `api-control`), no static mounts, no lifespan DB work. |
| `src/engine/api/deps.py` | Settings and (later) Redis dependencies. |
| `src/engine/api/routes/health.py` | `GET /health` (process alive) and `GET /ready` (catalog reachable; from Step 12, Redis reachable). |
| `docs/nautilus-api-notes.md` | Seeded with the version, the confirmed import table, and the indicators deviation from §II.1. |
| `tests/` | `tests/{data,dsl,backtest,api,fixtures}/` skeleton + `conftest.py`. |

Tooling: `ruff`, `mypy --strict` scoped to `dsl/`, `strategies/`, `backtest/` (§12), `pytest` + `pytest-asyncio` + `hypothesis`.

**Gate:** `uv run fastapi dev src/engine/api/app.py` serves `/health` and `/ready`; `uv run pytest` green; `uv run ruff check .` and `uv run mypy src` clean.

---

### Step 2 — Phase 0a · Catalog and instruments

- `src/engine/data/catalog.py` — thin wrapper over `ParquetDataCatalog` rooted at `NT_CATALOG_PATH`. Read/write bars, write instruments, list instruments, query available date range per `BarType`.
- `src/engine/data/instruments.py` — build a real Nautilus `Instrument` from exchange metadata (price precision, size precision, tick size, lot size, min notional) per §4.1(3). `TestInstrumentProvider` is confined to tests.

**Gate:** synthetic-bar round-trip test — write 500 bars, read them back, assert order and exact timestamps. No network in these tests.

---

### Step 3 — Phase 0b · Exchange fetcher and raw store

- `src/engine/data/sources/binance.py` — paged public-REST OHLCV fetch, rate-limit aware, exponential backoff on 429/5xx (§4.1 steps 1–2). Also fetches `exchangeInfo` to feed Step 2's instrument builder.
- `src/engine/data/raw.py` — persists the **unmodified** response under `NT_RAW_PATH` before any transformation, content-addressed and append-only. Never overwritten — it is the audit trail.

Written behind a `MarketDataSource` protocol so a second exchange is a new module, not an edit to `ingest.py` (§13 pitfall 6: do not build an ingestion API that makes a survivorship-free universe impossible later).

**Gate:** fetcher tested against recorded HTTP fixtures (no live network in CI); one manual live smoke fetch of a single day; retry/backoff path covered by a test that returns 429 then 200.

---

### Step 4 — Phase 0c · Ingest CLI and timestamp discipline

- `src/engine/data/ingest.py` with the exact CLI from §4.1, plus `--dry-run`.
- Raw rows → `Bar` conversion (§4.1 step 4).
- **Timestamp discipline (§4.2), as hard assertions that abort ingestion:** UTC integer nanoseconds; `ts_event` = bar **close** (Binance returns open — the interval is added, and there is a test that fails if that addition is removed); `ts_init == ts_event` for historical ingest; never `ts_init < ts_event`.
- Idempotent re-ingest of an already-covered window.

This is §13 pitfall 2 — the most common cause of a backtest that looks great and fails live — so the off-by-one-interval test is written before the conversion code.

**Gate:** ingest one week of 15m BTCUSDT; `catalog.bars(...)` returns close-aligned timestamps; a fixture with open-aligned timestamps fails the assertion.

---

### Step 5 ★ — Phase 0d · Quality monitors and Phase 0 acceptance

- `src/engine/data/quality.py` (§4.3): gap detection, duplicate `ts_event`, outlier flag (range > N× trailing median), zero-volume/zero-range counts, strict monotonicity.
- **Fails** ingestion on duplicates or non-monotonic timestamps; **warns** on gaps and outliers.
- Report written as a JSON artifact under `NT_ARTIFACT_PATH`. *(§4.3 says "written to Postgres", which §9.4 forbids for this service. Resolved the way §9.4 resolves the same conflict for backtest results: write the artifact locally, and POST the summary to `api-control` in Step 17. See Open Question Q2.)*

**Phase 0 acceptance (§4.4):** `uv run pytest tests/data` green · two years of 15m BTC/USDT bars in the catalog · `catalog.bars(...)` ordered and close-aligned · corrupted fixtures (duplicate row, out-of-order row, missing day) each caught.

**Gate:** all four of the above, demonstrated.

---

### Step 6 — Phase 1a · DSL schema and canonical hash

- `src/engine/dsl/schema.py` (§5.1): Pydantic v2, `frozen=True`, `extra="forbid"` on every model. Recursive `all`/`any`/`not` groups, discriminated unions for leaves (on `indicator` and on `type`), depth ≤ 5, leaves ≤ 32, `timeframe` a closed enum. **`Decimal` parsed from strings for anything touching price, quantity, notional or fees**; `int`/`float` only for indicator periods and thresholds.
- `src/engine/dsl/hashing.py`: canonical JSON serialization → SHA-256 → `spec_hash`. Stable across processes (needed for `strategyVersionId`), so: sorted keys, no whitespace, `Decimal` as string, explicit encoding.

**Gate:** `extra="forbid"` rejects a typo'd field; depth-6 and 33-leaf specs rejected; round-trip spec → JSON → spec byte-identical; hash identical across two separate interpreter processes (asserted by subprocess, not in-process, because `PYTHONHASHSEED` is the thing being guarded against).

---

### Step 7 — Phase 1b · Indicator registry

`src/engine/dsl/indicators.py` (§5.4): one dict, DSL name → `IndicatorSpec(factory, value)`. Ships `rsi`, `sma`, `ema`, `atr`, `volume` (the last read from the bar, not an indicator object).

Uses the flat imports confirmed in §II.1. **Adding an indicator must be one registry entry plus one test — if it needs an interpreter change, the abstraction is wrong.**

**Gate:** each registered indicator instantiates, warms up on a synthetic series, and reports `.initialized` at the expected bar count.

---

### Step 8 — Phase 1c · Interpreter

`src/engine/dsl/interpreter.py` (§5.3): `evaluate(node: ConditionNode, ctx: EvalContext) -> bool`.

- **Pure**: no I/O, no clock, no logging of mutable state; unit-testable without importing Nautilus.
- **No lookahead**: `EvalContext` is built only from data at or before the current bar's close, and there is a test constructing a context whose "future" fields are poisoned so any read fails.
- `crossesAbove` = previous ≤ threshold **and** current > threshold; `crossesBelow` symmetric; **`False` when the previous value is unavailable** (warmup), never a guess.
- Unknown indicator or operator **raises** (§13 pitfall 9 — no broad `except` returning `False`).

**Gate:** table-driven tests per operator including warmup boundaries and exact-equality edges; the lookahead test; the raise-on-unknown test.

---

### Step 9 ★ — Phase 1d · Validator and Phase 1 acceptance

`src/engine/dsl/validator.py` (§5.2). Returns a **list** of `SpecError(path, code, message, limit, observed)` — all problems at once, not the first. Checks: unsupported indicator/operator combination · indicator period exceeding available warmup for the requested window · empty `entry` or `exit` group · missing `stopLossPercent` when stops are required · symbol absent from the catalog · same indicator declared twice with conflicting parameters · pyramiding implied (rejected — one position per instrument in v1, §6).

**Phase 1 acceptance (§5.5):** Hypothesis property test — any spec passing schema + validator evaluates without raising on a synthetic bar series · per-operator table tests green · unknown indicator rejected at validation, not runtime · round-trip and cross-process hash stability.

**Gate:** the four above.

---

### Step 10 — Phase 2a · `DslStrategy` — wiring and evaluation

`src/engine/strategies/dsl_strategy.py`. One class, no code generation, ever (§0).

- `DslStrategyConfig(StrategyConfig, frozen=True)`: `instrument_id`, `bar_type`, `spec: dict`, `strategy_version_id`, `spec_hash`.
- `on_start`: resolve instrument from cache (abort loudly if missing) → build indicators from the registry → `register_indicator_for_bars` → `subscribe_bars`.
- `on_bar`: return early until every indicator `.initialized` → build `EvalContext` (current and previous values, position state, entry price, unrealised PnL %) → evaluate `entry` when flat, `exit` when in position.
- **No network, no file reads, no `datetime.now()`** — `self.clock` only.
- Log every signal decision with `strategy_version_id`, `spec_hash`, bar timestamp and per-condition results. This log is the "why did the agent trade" record.
- Docstring states **bar-close semantics** explicitly: signals evaluate on closed bars, entries submit for the next bar. Intrabar fills are a deliberate later decision.

**Gate:** strategy loads via `ImportableStrategyConfig` inside a `BacktestNode` on Step 5's catalog data, warms up, and logs decisions. Orders not yet required.

---

### Step 11 ★ — Phase 2b · Sizing, order lifecycle, and Phase 2 acceptance

- Sizing from `spec["sizing"]`. `riskPercent`: `qty = (equity × riskPercent) / (entry_price × stopLossPercent)`, then **rounded down** to the instrument's size precision, rejected below min notional. Never round up into more risk than the budget allows.
- Entry submission, exit/close, one position at a time per instrument.
- Fresh engine per run — no engine reuse across jobs (§13 pitfall 4).

**Phase 2 acceptance (§6):** end-to-end run in `BacktestNode` producing ≥ 1 round-trip trade · **determinism: same spec + same data + same seed → byte-identical fills across three runs**, asserted in a test that stays in CI · a never-triggering spec produces zero orders and does not raise.

**Gate:** the three above. The determinism test is the load-bearing one (§12) — it must not be weakened later.

---

### Step 12 — Phase 3a · Job store and idempotency

`src/engine/store/jobs.py` — job records in Redis (§9): `jobId`, `status ∈ QUEUED|RUNNING|SUCCEEDED|FAILED|CANCELLED`, `submittedAt`, `startedAt`, `finishedAt`, `error`, `result`, plus the request payload hash.

Idempotency (§7.2): `requestId` is the key. Same `requestId` + same payload → the existing job, never a second run. Same `requestId` + **different** payload → `409`. Implemented as an atomic Redis set-if-absent, not read-then-write.

`/ready` gains a Redis check.

**Gate:** concurrent duplicate submissions in a test yield exactly one job; a differing payload under the same `requestId` yields `409`.

---

### Step 13 — Phase 3b · Backtest builder (pure)

`src/engine/backtest/builder.py` (§7.3): `(request, spec) -> BacktestRunConfig`. No side effects, fully unit-testable.

- **Fees and slippage are mandatory.** Omitted → `422`, never defaulted to zero (§13 pitfall 3).
- **No `CacheConfig` in backtests** — in-memory cache only (§9.2, §13 pitfall 10). A test asserts that a backtest config carrying a cache database fails fast.
- The `ImportableStrategyConfig` construction is extracted into **one shared function** (`src/engine/strategies/config.py`) that Phase 5's `live/node.py` will also call. §10.2 makes this non-negotiable: if backtest and live diverge here, the platform's core guarantee is gone.

**Gate:** golden-file test on the produced `BacktestRunConfig` for a fixed request + spec; missing-fees test returns the `422` error code; cache-in-backtest test fails fast.

---

### Step 14 — Phase 3c · HTTP API

`src/engine/api/routes/backtests.py` and `catalog.py`, per §7.2:

| Route | Behaviour |
|---|---|
| `POST /v1/backtests` | Validate **synchronously** (schema + validator), then enqueue only. `202` `{jobId, status: "QUEUED"}` · `422` `{errors: [SpecError...]}` · `409` on conflicting `requestId`. |
| `GET /v1/backtests/{jobId}` | Job record. |
| `DELETE /v1/backtests/{jobId}` | Cancel if not yet running. |
| `GET /v1/catalog/instruments` | What can actually be backtested. |

Auth: static bearer from `NT_INTERNAL_API_KEY` in a dependency (§7.2). Nothing beyond that (§1).

**The handler never runs a backtest** (§7.1, §13 pitfall 1) — a test asserts the handler does no blocking work.

**Gate:** `422` for an invalid spec returns in **< 100 ms and never touches the queue**; auth rejects a missing/wrong token; the enqueue path is non-blocking.

---

### Step 15 — Phase 3d · Worker and runner

- `src/engine/worker/main.py` + `tasks.py` — arq worker, `NT_REDIS_URL`.
- `src/engine/backtest/runner.py` (§7.4) — fresh `BacktestNode` per job → `.run()` → retrieve engine by run-config ID → `generate_order_fills_report()`, `generate_positions_report()`, account report → **explicit `dispose()`** and drop.
- Wall-clock timeout → `FAILED` with `code: "TIMEOUT"`.
- Exceptions: traceback persisted to the job record, **never** leaked in the HTTP response beyond a code and short message.
- `max_jobs` per worker process with recycling, because Nautilus engines hold significant memory (§7.4).

**Gate:** a job runs to `SUCCEEDED` end-to-end; an intentionally slow job hits `TIMEOUT`; a raising job records the traceback internally and returns only a code.

---

### Step 16 — Phase 3e · Results and artifacts

- `src/engine/backtest/results.py` (§7.5) — summary metrics: total return, CAGR, max drawdown, Sharpe, Sortino, win rate, profit factor, trade count, average and median trade, average holding period, total fees paid, **total slippage cost**, exposure percent.
- `src/engine/store/artifacts.py` — series to parquet under `NT_ARTIFACT_PATH`: equity curve, drawdown curve, per-trade table (entry/exit time, price, quantity, fees, slippage, PnL, **and the triggering condition**).
- API response returns the summary plus artifact IDs/URLs. **A 50k-row equity curve is never inlined in JSON.**
- All money values `Decimal` end to end (§12, §13 pitfall 7).

**Gate:** golden-file test of the summary on a small fixed dataset — a diff means behaviour changed, which must be deliberate (§12).

---

### Step 17 ★ — Phase 3f · Phase 3 acceptance, deployment, result hand-off

- `docker-compose.yml`: `api` + `worker` + `redis`, with the catalog and artifact paths mounted. `Dockerfile` gains a worker target.
- Optional completion webhook to a caller-supplied URL (§7.2) — poll-first is fine for v1.
- POST the backtest summary (and the Step 5 quality report) to `api-control` on completion, per §9.4. **This service never opens a connection to the platform Postgres, in any phase.** Gated on Open Question Q1.

**Phase 3 acceptance (§7.6):** submit → poll → `SUCCEEDED` with a summary against real catalog data, as an integration test · duplicate `requestId` returns the same `jobId` and does not double-run · invalid spec `422` in < 100 ms without touching the queue · **worker survives 50 sequential jobs within an asserted RSS ceiling**.

**Gate:** the four above, plus `docker compose up` serving a real submitted backtest.

---

### Step 18 ★ — Phase 4 · The milestone that actually matters

Reproduce a published backtest within tolerance (§8).

Pick a target with published, reproducible results and stated data, fees and period. Express it in the DSL. Run it through this service. Compare. Record in `docs/reproduction-<name>.md`: source, data used, fee assumptions, expected metrics, achieved metrics, delta, and an explanation for every delta.

**If the numbers miss tolerance, stop and fix the data or the simulator. Phase 5 does not start.** Every downstream number is meaningless until this passes. See Open Question Q3 for target selection.

**Gate:** the reproduction document exists and its deltas are explained, not merely reported.

---

### Steps 19–23 — Phase 5 · Live runtime

The gate opened when Steps 0–18 went green and `docs/adr-001-live-execution.md`
was written. That ADR chose **Option B**: Nautilus's `TradingNode` submits
orders to the venue directly, and nothing else sends a live trade. It also lists
seven conditions before a real key is loaded, **none of which are met** — so
`TradingMode.LIVE` refuses to build a node, and paper is the only mode that runs.

### Step 19 — Phase 5a · Desired state and supervisor

Redis-backed desired-state records (`PUT /v1/live/{accountId}` as a desired
state, not a job) · observed state with heartbeats and leases · a supervisor
loop that closes the four gaps between them (should-run-and-is-not,
should-not-and-is, running-the-wrong-spec, heartbeat-expired) · `HALTED` as a
state a supervisor will not restart out of.

### Step 20 — Phase 5b · The node, paper only

`build_node_config` as a pure function · the shared `strategy_config()` factory,
so a live node's strategy config is identical in shape to a backtest's · Redis
cache on a **different Redis instance** from arq, asserted (D15: `DatabaseConfig`
exposes no DB index, so a logical DB is not separation) · `flush_on_start=False`
· credentials that redact in `repr` and are never defaulted.

### Step 21 — Phase 5c · Startup reconciliation

Cache, then venue, then compare, then start — in that order. A disagreement
raises and halts the account rather than restarting it: a node that starts
trading on unverified state is worse than one that stays down.

### Step 22 — Phase 5d · Kill switch and account-level risk limits

ADR-001 moved the risk kernel's job into this process, so these checks are the
only thing between a strategy and the account when `trading-core` is down.

* **Account-level, not strategy-level.** Five strategies each inside a
  per-strategy limit is one bet at five times the size.
* **The kill switch answers first and alone** — no limit arithmetic, no account
  state, no venue call.
* **More than one path to it**: a flag in this service's Redis (fast, remote,
  and deliberately not in `trading-core`) and a file on the node's own disk
  (works when Redis does not). Engaged when either says so, **or when either
  errors** — a path that cannot answer is treated as engaged.
* **Reduce-only orders are exempt from every limit but the kill switch.**
  Refusing to close would trap the account in the position that breached it.
* **The order path reads a snapshot, never the network.** `on_bar` is
  synchronous on the loop carrying the venue's websocket. The gate is refreshed
  by the heartbeat task; a snapshot older than `max_age` counts as engaged, so a
  node whose refresh loop dies stops opening risk and keeps every means of
  shedding it — and the same silence brings the supervisor.

A backtest gets `NoGate`, a null object, so backtest and live run one order path
and results stay byte-identical.

### Step 23 ★ — Phase 5e · Phase 5 acceptance

`kill -9` mid-position, restart, recover from the cache, and match a stubbed
venue. The acceptance test for everything above.

### Steps 24+ — the control plane's front door and process isolation

**Step 24** — `engine.live.main`, the entry point Phase 5 shipped without.
**Step 25** — `engine.simulation`, so the three environments each have a package.
**Step 26** — one OS process per account, which section 10.1 had asked for from
the beginning.

Recorded in §II.13, §II.14 and §II.15.

### Phase 6 — deleted by ADR-001

**§11 of this document is dead.** Its own heading says "Option A only", and
ADR-001 chose Option B: Nautilus's `TradingNode` submits orders to the venue
directly, and nothing else sends a live trade. The ADR is explicit that "spec
§11 describes roughly a phase of work that this decision deletes".

Gone with it: the `TradeIntent` schema, the custom execution client that
published instead of trading, idempotent inbound fill consumption, the
bounded-wait-then-pause protocol for an intent that got no answer, and
reconciling against two views of the truth. **Every one of those was a place
for two systems to disagree about what happened.**

**Do not build any of it.** If a future step looks like it needs a `TradeIntent`,
the question to ask is whether Option B is still the decision — not whether to
add the bridge back quietly.

### What replaces it, and it is a step rather than a phase

Fills still have to reach `api-control`, which owns the ledger. That is
**outbound reporting, not an execution path**, and the difference is the whole
point of the ADR:

* **One way.** Nothing waits for a reply, so there is no bounded wait and no
  pause protocol.
* **Not the record.** Nautilus's cache is the record; this is a copy for the
  ledger and the UI. A publish that fails is a gap in reporting, not a lost
  order.
* **The mechanism already exists.** `store/publish.py` POSTs backtest summaries
  to `api-control` today; live fills are the same shape.

It belongs after the soak, and it is roughly a day.

## II.4 What this plan deliberately does not build

Restating §1 so it does not erode step by step: no real-venue execution, no credential storage or KMS, no risk kernel or mandates or approvals (those are TypeScript `trading-core`), no LLM or strategy authoring, no auth beyond the shared internal secret, no UI. And, from §9.4: **no connection to the platform PostgreSQL, in any phase.**

## II.5 Decisions taken

Resolved by the repo owner on 2026-09-04, before Step 1.

**D1 — Package name: `engine`.** `src/engine/`, so `strategy_path` reads
`engine.strategies.dsl_strategy:DslStrategy`. That string is embedded in stored
strategy configs, so it is settled now rather than later.

**D2 — Phase 0 ingests Binance *spot* BTC/USDT, 15m**, per Part I's examples.
`CurrencyPair` instrument, `CASH` account, no funding rates. The sibling
`Trading-Engine` repo holds USD-M perpetual-futures data and fetch code; it is
**reference only** and its catalog is not reused. Perps remain possible later
behind the `MarketDataSource` protocol introduced in Step 3, and would add
funding rates as a second ingest stream.

**D3 — `api-control` does not exist yet; it is built later, in TypeScript.**
Consequences, which Steps 5 and 17 must honour:

- The result hand-off is built **inert, not absent**. Steps 5 and 17 write the
  POST and test it against a `respx` stub, gated behind `NT_API_CONTROL_URL`,
  which is unset by default. Wiring it up later is a config change, not code.
- Artifacts (quality reports, backtest summaries and series) land locally under
  `NT_ARTIFACT_PATH` until that endpoint exists.
- Poll-first covers the gap: §7.2 makes `GET /v1/backtests/{jobId}` the contract
  and the webhook optional, so nothing is missing in the meantime.
- **This does not license a Postgres connection.** "No `api-control` yet" must
  never become "let the Python service write the tables directly" — §9.4 and
  rule 2 of `CLAUDE.md`. That shortcut is very hard to undo once results are in
  a table.

**D4 — This is a pure Python project.** The template's `package.json` was
authored for a pnpm monorepo that does not exist in this tree; it is deleted and
`uv` is the only task runner.

## II.6 Still open

**Q1 — Reproduction target for Phase 4 (Step 18).** Needs a named target with
published metrics, stated fees and a stated period. Candidates: a documented
NautilusTrader example, or a public strategy with fully specified assumptions.
Reviewer to pick, or delegate the pick. Not blocking until Step 18.

**Q2 — §4.3 vs §9.4 on the quality report.** §4.3 says quality results go "to
Postgres"; §9.4 forbids this service from touching Postgres. Resolved in the
plan the way §9.4 resolves the identical conflict for backtest results — local
artifact plus POST to `api-control` (see D3). Flagged rather than open: raise it
only if the intent was different.

---

## II.7 Phase 0 acceptance record

Recorded 2026-09-07, on completion of Step 5.

**Catalog:** `BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL`, Binance spot, ingested
from the public REST API over `2023-01-01 .. 2025-01-01`.

| Criterion (§4.4) | Result |
|---|---|
| `uv run pytest tests/data` green | 141 passed |
| Two years of 15m BTC/USDT in the catalog | **70,171 bars** |
| `catalog.bars(...)` returns them in order | ordered, no duplicates |
| Close-aligned timestamps | first close `2023-01-01T00:15:00Z`, last `2025-01-01T00:00:00Z`, all on the 15m grid, `ts_init == ts_event` throughout |
| Corrupted fixtures caught | duplicate row, out-of-order row and missing day each caught — `tests/data/test_quality.py` |

**The 5-bar shortfall is real, and explained.** A perfect series over these 731
days (2024 is a leap year) would hold 70,176 bars. The quality report finds
exactly one gap, of exactly 5 bars, on 2023-03-24 between 12:45Z and 14:15Z —
and the five bars immediately preceding it are flagged `ZERO_RANGE` *and*
`ZERO_VOLUME`. That is the signature of an exchange incident: the market froze
for 75 minutes, then the feed stopped altogether. The monitors did not find
noise; they found a datable event and described its shape.

Remaining findings, all warnings: `OUTLIER_RANGE=115` (0.16% of bars, against a
10x trailing-median threshold — crypto volatility, not corruption).

**Re-running the identical ingest command fetches nothing.** Coverage is checked
in close space and only gaps are fetched, so a repeated ingest is a no-op.

Footprint: catalog 5.0M (72 parquet files), raw 13M (71 responses), artifacts 24K.

**Phase 0 is closed. Step 6 — the DSL schema — may begin.**

---

## II.8 Phase 1 acceptance record

Recorded 2026-09-07, on completion of Step 9.

| Criterion (§5.5) | Result |
|---|---|
| Property test: any spec passing schema + validator evaluates without raising | 200 generated specs per run, **79% reach the interpreter**; a separate test fails if that share drops below 25%, so the property cannot go vacuous |
| Table-driven tests per operator, incl. warmup boundaries and exact-equality edges | 6 comparison cases, 12 crossing cases, 8 exit cases |
| A spec with an unknown indicator is rejected at validation, not at runtime | The schema's discriminated union refuses it; the validator reports `UNKNOWN_INDICATOR` for hand-built specs |
| Round-trip spec → JSON → spec byte-identical, SHA-256 stable across processes | Asserted in-process and across three subprocesses with `PYTHONHASHSEED` 0, 1 and 424242 |

387 tests green; ruff and mypy clean.

**Two notes for later phases.**

*The interpreter is genuinely Nautilus-free.* §5.3 requires it be unit-testable
without Nautilus, so series-name derivation moved into a new pure module,
`dsl/keys.py` (a deviation from the Part II file list). `indicators.py` is the
only file under `dsl/` that imports Nautilus. Two tests parse the ASTs of
`interpreter.py` and `keys.py` and fail on a Nautilus, clock, or I/O import, and
importing the interpreter is asserted to pull in no `nautilus_trader` module at
all.

*§5.2's "same indicator declared twice with conflicting parameters" is
unrepresentable here.* Series identity is `(indicator, period)`, so two
declarations either resolve to the same series — and share one instance — or to
genuinely different ones. An SMA crossover is two SMAs and must stay legal.
What is reported instead is `DUPLICATE_CONDITION`: a byte-identical leaf
repeated in the same tree, which is redundant rather than contradictory and is
the shape generated specs actually take.

**Phase 1 is closed. Phase 2 — `DslStrategy` — may begin when the repo owner
says so.**

---

## II.9 Phase 2 acceptance record

Recorded 2026-09-07, on completion of Step 11.

Run against the Phase 0 catalog: Binance spot BTC/USDT 15m, `2024-01-01` to
`2024-03-01`, `10000 USDT` starting balance, RSI(14) crossing above 30 to enter.

| Criterion (§6) | Result |
|---|---|
| Runs end to end in a `BacktestNode` and produces at least one round-trip trade | **27 closed positions**, 55 fills |
| Same spec + same data + same config → byte-identical fills across three runs | Asserted over the entire fills report less one column; see below |
| A spec that never triggers produces zero orders and does not raise | Zero orders, zero positions, no exception |

441 tests green; ruff and mypy clean.

**On "byte-identical".** Across repeated runs of an identical config, exactly
one column of the fills report varies: `init_id`, a UUID4 minted per
order-initialized event. Prices, quantities, slippage, commissions, `ts_init`,
`ts_last`, `position_id`, `venue_order_id` and `last_trade_id` are all
identical. The determinism test compares the whole report less that one column,
and a second test pins the exclusion list — so if Nautilus ever makes another
column random, that fails rather than the exclusion quietly growing. See
`docs/nautilus-api-notes.md` D9.

**Sizing is exact.** `quantity = (equity × riskPercent) / (price ×
stopLossPercent)`, so being stopped out costs precisely `riskPercent` of
equity. Verified for four risk/stop combinations. Quantity is floored to the
venue's step size, never rounded to nearest: rounding up would put more at risk
than the budget allows, silently, on every trade. Where the risk budget implies
more than the account can pay for, the position is capped and the caller is
told — capping only ever reduces it.

**Bar-close semantics are observable.** With only percentage exits configured,
every winning trade closes at or beyond +4% and every loser at or beyond −2%,
never before. The overshoot is the signal being computed on a closed bar and
filling on the next one, which is what §6 requires; an exit landing exactly on
its threshold would mean something was filling intrabar.

**Phase 2 is closed. Phase 3 — the backtest job service — may begin when the
repo owner says so.**

---

## II.10 Phase 3 acceptance record

Recorded 2026-09-08, on completion of Step 17.

| Criterion (§7.6) | Result |
|---|---|
| Submit → poll → `SUCCEEDED` with a summary, against real catalog data | Integration test through the real API, claim, runner and Parquet writer; only the arq daemon is absent, and the task is invoked exactly as arq invokes it |
| Duplicate `requestId` returns the same `jobId` and does not double-run | Same `jobId`, `200` rather than `202`, one queue entry, and `finished_at` unchanged after a second worker pass |
| Invalid spec `422` in under 100 ms without touching the queue | **2.6 ms** live; the test asserts the slowest of five under 100 ms with an empty queue |
| Worker survives 50 sequential jobs within an asserted RSS ceiling | **No growth at all** |

646+ tests green; ruff and mypy clean.

**The memory result.** Fifty real backtests, each in its own child process:

```
baseline after warmup: 345 MB
  after 10 jobs: 345 MB  (growth +0 MB)
  after 20 jobs: 345 MB  (growth -0 MB)
  after 30 jobs: 344 MB  (growth -1 MB)
  after 40 jobs: 343 MB  (growth -2 MB)
  after 50 jobs: 343 MB  (growth -2 MB)
```

Resident memory does not merely stay under a ceiling; it is flat, and drifts
slightly downward. That is the subprocess design doing what §7.4 asks: a
Nautilus engine holds a lot of memory, and a process that exits returns all of
it. The test asserts both an absolute ceiling and that the second half's mean
does not exceed the first's — a slow leak stays under a ceiling for fifty jobs
and takes the box down at five hundred.

The 50-job tests are marked `slow` (100 real backtests, ~79 s). Deselect with
`uv run pytest -m "not slow"`; they run by default, because an acceptance gate
that is skipped is not a gate.

**Deployment.** `docker-compose.yml` now runs `api`, `worker` and `redis`.
`api` and `worker` are separate services because §7.1 forbids ever running a
backtest inside the HTTP process. Scale with
`docker compose up --scale worker=4`; each worker takes one backtest at a time,
because a backtest saturates a core.

**The api-control hand-off is built and inert**, per decision D3 in §II.5.
`NT_API_CONTROL_URL` is unset by default; with it unset, `publish_result`
does nothing and reports `published: false`, and results stay local and
pollable. A publish failure never fails a completed job — the run happened and
its numbers are stored; losing the hand-off is recoverable by re-publishing,
whereas failing the run is not.

**Phase 3 is closed. Phase 4 — reproducing a published backtest — may begin
when the repo owner says so.**

---

## II.11 Phase 4 acceptance record

Recorded 2026-09-08, on completion of Step 18.

**Reproduced:** SMA(10) × SMA(20) crossover on GOOG daily, 2004-08-19 →
2013-03-01, $10,000, 20 bps commission, against `backtesting.py` 0.6.6.

| Metric | backtesting.py | this service | delta |
|---|---|---|---|
| trades | 46 | 46 | 0 |
| win rate | 52.1739% | 52.1739% | 0 |
| closed-trade profit | $41,753.20 | $41,753.18 | **$0.016** |
| final equity | $59,522.09 | $59,522.08 | **$0.01** |
| total return | 495.2209% | 495.2208% | **0.0001 pp** |

Zero divergence across all 46 trades on quantity, entry price and exit price.
Full write-up in `docs/reproduction-sma-cross-goog.md`; the comparison runs as
a test in `tests/reproduction/test_cross_engine.py`.

721 tests green; ruff and mypy clean.

**The target changed, for a reason worth recording.** The intended benchmark
was `backtesting.py`'s published figure — 718.12% return, Sharpe 0.72. It does
not reproduce: their own library at version 0.6.6 gives 462.64%, while the
data-derived metrics (Buy & Hold, Exposure) match the published values to every
digit. The data is identical and the engine changed between versions. A
published backtest therefore needs one more thing nobody states: **the version
of the engine that produced it.** Recorded in
`docs/reproduction-benchmark-search.md`.

The reference became the *running* engine rather than its published number,
which is stronger: a delta against a running engine can be investigated rather
than guessed at.

**Six defects found across Phase 4, all in the simulator.**

| | |
|---|---|
| D13 | RSI defaulted to EXPONENTIAL, not Wilder — up to 34 points out; a losing month became a winning one |
| D12 | Orders fill at the signal bar's close, not the next bar's open |
| D14 | Position prices returned as floats, landing float noise in a Decimal money field |
| — | Adding one optional schema field changed `spec_hash` for every spec ever written |
| — | Sizing did not reserve for its own commission; the account overdrew and the exchange **halted the run** |
| — | A halted run reported `SUCCEEDED`, indistinguishable from a short but legitimate result |

None of these were visible from inside. Four needed an independent
implementation to see, and two needed a different market: the sizing overdraw
cannot occur at 1% risk with a 2% stop, where a position is half the balance
and always has the headroom to hide it.

**D12 is now priced rather than assumed.** Toggling the reference's
`trade_on_close` isolates it exactly: filling at the signal bar's close costs
**8.5 percentage points of win rate** on daily equities. On BTCUSDT 15m the same
assumption was measured at effectively nothing — `close[t]` equals `open[t+1]`
on 49% of bars. The conclusion "harmless on a continuous market, must be
revisited on a gapping one" is now evidence.

**Two capabilities were added because the reproduction needed them**, and both
are general:

* indicator-vs-indicator comparison, so the moving-average crossover family is
  expressible at all — without it no published benchmark was reachable;
* a `CsvSource`, so a dataset that no crypto exchange serves can be ingested
  through the normal path, raw recorded first and quality monitors run.

**Phase 4 is closed. Phase 5 is gated on `docs/adr-001-live-execution.md`,
which does not exist.**

## II.12 Phase 5 acceptance record

`tests/test_phase5_acceptance.py` — **22 tests, green.** Suite total 909;
`ruff` and `mypy --strict` clean.

### What was proven

| Criterion | How |
|---|---|
| A `SIGKILL` runs no cleanup | A real child process, a real `SIGKILL`, a `finally` that must not run |
| A killed node is noticed | The record still says `RUNNING`; only the stale heartbeat gives it away |
| It comes back **once** | Five further passes find nothing to do; `starts == 2` |
| A quiet node is left alone | 178 s with a heartbeat halfway: no restart |
| Reconciliation precedes the build | A disagreeing venue raises `ReconciliationFailed`, an agreeing one gets as far as `LiveNotPermitted` |
| A disagreement halts | And ten passes over 600 s start nothing |
| Only an operator clears it | A new revision does; time does not |
| One node per account | A second supervisor is refused; two racing passes produce one node |
| A stop outlives the process | A kill engaged before the crash is still engaged on the rebuilt gate |
| Redis down ≠ kill switch down | The file path still stops the account; an unreadable path counts as engaged |

### One defect found, in the supervisor

**A halted account could not be stopped.** `_reconcile_account` acted on a
`STOPPED` desire only when the observed status `is_live`, and `HALTED` is not.
So `desired=STOPPED` and `observed=HALTED` never converged: the operator saw
`HALTED` forever with no way to say "I am done with it", and `FAILED` had the
same hole.

Worth naming precisely, because the Step 19 test *asserted the bug* under a
comment describing the fix — "Halted must not mean unreachable: stopping is the
one thing that should always work", followed by an assertion that stopping did
nothing. A test can hold a mistake still while reading as though it caught it.

The condition is now "any status but `STOPPED`". `runner.stop()` is idempotent,
so stopping something that never started costs nothing.

### What is deliberately not asserted

Nautilus's own cache recovery — rebuilding orders and positions from Redis —
would need a real Redis instance and a real venue, which ADR-001 forbids this
repo from having. What is ours is tested: that an abrupt death is noticed, that
exactly one node returns, that it does not return trading on state the venue
disagrees with, and that a stop survives the process it stopped.

### Phase 5 is closed

Live remains **gated**: ADR-001's seven conditions are still zero-of-seven met,
so `TradingMode.LIVE` refuses to build a node and paper is the only mode that
runs. That is the intended end state — Phase 5 delivers a live *runtime*, not a
live *account*.

**Since resolved: ADR-002, where the risk kernel runs** —
`docs/adr-002-risk-kernel.md`, accepted 2026-09-08. All three sub-decisions
taken: mandates do not expire and are revoked explicitly, revocation blocks new
entries while permitting exits, and the kill switch stays as Step 22 built it.
See §II.18. What remains before a real key is the mandate itself — schema,
revocation path, and a node that refuses to start without one.

## II.13 Step 24 — The control plane's entry point

Phase 5 built a supervisor, a node runner, a risk gate and a kill switch, and
nothing that starts them. `grep -rn "LiveNodeRunner(" src/` returned nothing:
a complete, tested control plane with no front door.

```bash
uv run python -m engine.live.main
```

`engine/live/main.py` is deliberately thin — construction and shutdown, with
every decision left in the objects it builds. What it owns is the wiring that
must not be got wrong:

* the kill switch is a **composite** of Redis and a file on the node's own
  disk, so an operator keeps a path to the account when one is unreachable —
  a single-path switch passes every test the switch has and fails only on the
  day the path it uses is the broken one;
* `holder` is `hostname:pid`, so a lease says *which process* holds an account
  rather than merely that someone does;
* a `SIGTERM` stops the nodes, marks them `STOPPED` and releases the leases, so
  the next supervisor picks the accounts up on its next pass rather than after
  a 90-second heartbeat timeout.

### A hazard found while building it — D16

`TradingNode(config)` **blocks forever** when its cache Redis is unreachable,
and does not die on `SIGTERM` — measured at 346 seconds before `SIGKILL`.

`Supervisor._start` awaits `runner.start()`, and the pass is sequential, so one
unreachable Redis would stall the loop for **every** account, with no error, no
log line and no exit. `preflight()` now pings both Redis instances before the
supervisor is constructed and names which one is down. A deploy that fails
beats a deploy that wedges.

**Residual risk, stated rather than fixed:** the preflight covers boot, not a
Redis that dies while running. Bounding `start()` with a timeout means running
a blocking constructor in a thread and leaking it when it never returns — a
worse trade than it looks, and better decided against a real deployment. The
soak run is where to revisit it.

### What is deliberately still missing

**Venue reconciliation is not wired, and cannot be.** Reading what a venue holds
means private endpoints, which means a key, which ADR-001 forbids. Paper has no
venue state to disagree with; live is gated. The `CacheReader` and `VenueReader`
protocols stay behind their interfaces until the step that loads the first key,
and `LiveNodeRunner` already refuses to start a live account without them.

**`LiveNodeRunner.start()` still has not run against a real feed.** Every test
calls `_reconcile` or `_attach_gate` directly. That is what the soak run is for:
a websocket that reconnects, a venue that rate-limits, a market that goes quiet
at 3am — the class of problem a stub cannot produce.

## II.14 Step 25 — Three environments, and the node that never booted

`engine.simulation` now exists beside `engine.backtest` and `engine.live`, so
the three ways a strategy runs each have a package and one name:

| Environment | Package | Data | Execution | Money |
|---|---|---|---|---|
| `backtest` | `engine.backtest` | historical, from the catalog | simulated | none |
| `sandbox` | `engine.simulation` | **live**, from the venue | simulated | none |
| `live` | `engine.live` | live | **real** | real |

`engine.live` keeps the control plane — desired state, supervisor, gate, kill
switch, recovery — which is mode-agnostic and supervises all of them.
`TradingMode.PAPER` is renamed **`SIMULATION`**, so the mode, the package and
the value Nautilus is given (`Environment.SANDBOX`) all say the same word.
Three names for one thing is how a node ends up declaring itself live while
running a simulated exchange, which is exactly what it was doing.

### Five defects, found by one test that builds a node

Every one produces a **running, healthy-looking node**. None raise. Recorded as
D17 and D18.

| # | Defect | What it looked like |
|---|---|---|
| 1 | `environment` left at Nautilus's `LIVE` default | A sandbox node declaring itself live |
| 2 | No client factory registered | Node builds, starts, heartbeats, **trades nothing** |
| 3 | The pure fix breaks: `ImportableConfig` hands the builder an instance, and it checks `factory.__name__` | `AttributeError` at build |
| 4 | `venue` typed `Venue`, accepts a `str`, fails in Cython much later | `TypeError` at build |
| 5 | **`dispose()` closes the shared event loop** | Stopping one account kills the control plane |

Defect 2 deserves its own line, because it is the shape the others share:
`TradingNodeBuilder` logs a missing factory at ERROR and then `continue`s. A
node with no data client and no execution client builds successfully and reports
itself healthy. It is indistinguishable from a strategy that found no signals.
There is a test that reproduces it deliberately.

Defect 5 is the serious one. `LiveNodeRunner.stop` called `node.dispose()`,
which calls `loop.stop()` and `loop.close()` — on the loop shared by the
supervisor and every other account. **In a control plane whose purpose is
surviving the failure of one account, the stop path was a single point of
failure.** It now stops without disposing, and a test asserts the loop survives.

### The lesson, which is worth more than the five fixes

Configuration tests cannot find any of these, because every configuration was
valid. The object graph is only assembled at `build()`, and that is the first
moment any of it is checkable. **A boot test is not a nicety here — it is the
only place this class of defect is visible**, and Phase 5 shipped without one.

`tests/simulation/test_boot.py` builds a real node against a real Redis and
skips without one; `tests/simulation/test_node.py` holds what runs everywhere.
They are deliberately a pair: a skipped test catches nothing.

### Still open

**Process isolation.** Section 10.1 says an account is "the unit of process
isolation", the code comments repeat it, and the implementation runs every
account in one process on one loop. That is what made defect 5 possible. One OS
process per account makes `dispose()` safe, makes a crashing node crash alone,
and should be done before more than one account runs on a box.

**The soak.** `LiveNodeRunner.start()` has now been executed — by a test, for
the first time. It has still never met a live feed.

## II.15 Step 26 — One process per account

Section 10.1 has said from the beginning that "an account is the unit of risk,
credentials and reconciliation, so it is the unit of process isolation". The
code comments repeated it. Every account ran in one process, on one event loop.

That was not a stylistic gap:

* **`dispose()` closed the shared loop.** Stopping one account would have taken
  the supervisor and every other account with it (D18).
* **A crash was never contained.** A segfault in a native extension, an OOM
  kill, or an exception escaping a Cython callback ends a process. One process
  meant every account shared every fatal fault.

### What changed

| | Before | After |
|---|---|---|
| Node | held by `LiveNodeRunner` | in a spawned child, `engine.live.worker` |
| Gate and heartbeat | parent asyncio tasks | the child's own loop |
| Liveness | a timestamp, interpreted | `process.is_alive()`, the OS's answer |
| Stop | `node.stop()`, no dispose, leaks | SIGTERM → grace → SIGKILL; the process exits |
| Cleanup | code that had to be right | the operating system |

The parent holds **no Nautilus object at all** — a test asserts the attribute
does not exist. What crosses the boundary is JSON, the same discipline the
backtest runner uses, and for the same reason: spawn, never fork, because the
parent holds an asyncio loop, Redis connections and Nautilus state that do not
survive a fork intact.

**Disposing is no longer needed anywhere.** It exists to release a node's memory
and close its loop; the child exits immediately after stopping, so the operating
system does both — unconditionally, and without a timeout. That is the quiet
benefit of isolation: cleanup stops being something code has to get right.

The cost is a fresh interpreter and a fresh `nautilus_trader` import per account
start — seconds, not milliseconds. An account start is not on a hot path, and
the alternative is a shared-fate process.

### Two more defects, found by starting a real child — D19

Both make a node look healthy while being anything but.

**Nautilus replaces the child's `SIGTERM` handler.** The node shut down
correctly on `terminate()` and the process kept running, because the stop event
it was waiting on was never set. Every stop became a 20-second wait and a
SIGKILL. The child now waits on `node.run_async()` as well, so Nautilus's
handler is what ends the process.

Measured: a healthy node stops in **10.3 s**, inside Nautilus's
`timeout_disconnection`. **A stop grace shorter than that makes every ordinary
stop a kill**, which is why the default is 20 s and why the relationship is
written where the value is set.

**A live node's cache starts empty.** A backtest is handed its instruments from
the catalog; a live node must fetch them, and the default provider config loads
nothing. `DslStrategy.on_start` raised, the node's start halted, and the process
exited with status **0** — indistinguishable from a clean shutdown. Fixed with
`InstrumentProviderConfig(load_ids=...)` on both clients.

### A `DslStrategy` has now run against the live Binance feed

```
[INFO] NT-T.DataClient-BINANCE: RUNNING
[INFO] NT-T.DslStrategy: RUNNING
[INFO] NT-T.TradingNode: RUNNING
```

First time in the project's life. `tests/simulation/test_boot.py` starts a real
child, waits long enough for a failing one to have failed, and asserts it is
still there — gated on a reachable Redis *and* a reachable venue, and marked
`slow` so it can be deselected.

**The soak is now the next thing, and it is now possible.** What has been proven
is that a node starts, runs and stops. What has not is what happens over days: a
websocket that reconnects, a venue that rate-limits, a market that goes quiet.

## II.16 Step 27 — Two things that bite during a soak

Both found by asking what would happen if the control plane ran unattended for
a week rather than for a test.

### A crash loop, bounded

A child that dies during startup left nothing running, so every pass found
nothing running and started it again — every five seconds, forever. **Every
live defect found so far (D17, D18, D19) has been a startup failure**, which is
precisely the shape that loops. Against a real venue it is also how an IP gets
rate-limited.

The supervisor now backs off: five seconds, doubling, capped at five minutes.
Three details carry the design:

* **A start is judged after the fact, by how long the node lived.** Ten seconds
  in the process table is not a successful start; sixty seconds of running is.
  Without this the loop is invisible, because each individual start "worked".
* **Deferred, never abandoned.** The cap is bounded so an account that starts
  failing at 03:00 is still being retried at 09:00, roughly every five minutes.
* **An operator's restatement skips it.** A new revision is a new thing to try,
  not a retry of the failing one — the same gesture that clears a halt. So is a
  stop: asking for one is not a failed start.

A node that heartbeated for an hour and then wedged is restarted immediately;
one that wedges within seconds every time is not. Backoff state is per account
and in memory, so a supervisor restart clears it — the right trade, since the
new process has no evidence the account is still broken.

### Sizing that reserves for its own commission

I had this wrong first time and the correction is worth recording. **Simulated
fills are not free**: the sandbox client hardcodes `MakerTakerFeeModel`, which
charges the instrument's real Binance maker/taker rates. The gap was narrower
and worse — *sizing* did not know about them.

`cost_bps` was passed as `"0"` for live and simulation, because a live node has
no request to state fees in. So sizing left no room for the commission the
venue then charged. That is the **Phase 3 defect** exactly: the account
overdraws, the exchange halts the run, and three of forty-seven trades execute
under a result that reports success.

`DslStrategy` now resolves its cost rate at `on_start`:

| Source | When | Why it is right |
|---|---|---|
| `cost_bps` from the config | a backtest | The request states its fees, mandatory and never defaulted (rule 5) |
| The instrument's `taker_fee` | live and simulation | There is no request; the venue is the authority, and the node just fetched the instrument from it |

Which source won is logged either way, because "why is my size different here"
is otherwise unanswerable. Zero from both is left at zero — a venue that
charges nothing is a real answer and must not be turned into a guess.

## II.17 Step 28 — Declared fees, and the soak

The soak started, and told us something in its first minute.

### Fees have to be declared, because the venue will not say

`DslStrategy: cost rate 0 (from config)` — because a Binance instrument loaded
from the public endpoint reports `maker_fee: 0, taker_fee: 0` (D20). Real rates
are account-specific and behind an authenticated endpoint, which needs a key,
which ADR-001 forbids. The Step 27 fallback -- resolve the cost from the
instrument -- was the right mechanism on a wrong assumption.

`VenueFees` is now **required** on a live account: maker, taker and slippage,
exactly as a backtest request carries them (rule 5), with
`cost_bps = taker + slippage` matching `backtest/builder.py` so a strategy is
sized identically in both. A *declared* zero is allowed — a venue that charges
nothing is a real answer. A defaulted one is not.

The instrument fallback stays, below the declaration: it is right for any venue
that does report fees, and it is what an authenticated provider would populate.

### One bad record was stalling every account

Adding a required field made every record written before it unparseable — and
`reconcile_once` raised out of its loop, so **one account's unreadable record
stopped the pass for all of them**. A local failure with a global blast radius,
the same shape as the crash loop bounded in Step 27.

Each account is now isolated, and an unreadable record **leaves its node
running**. The node holds the position; the record only describes it. Stopping a
live node because its description went bad turns a bookkeeping problem into a
market one.

### The soak, as started

`run/soak-account.json` is the request body — the only worked example of a live
`PUT` in the repo, kept for that reason.

| | |
|---|---|
| Account | `soak_btc`, `SIMULATION` |
| Instrument | `BTCUSDT.BINANCE`, 15m |
| Strategy | RSI(14) crosses above 30, TP 4% / SL 2%, 1% risk |
| Fees | 10 bps maker, 10 bps taker, 5 bps slippage |
| Limits | 500 order, 1000 position, 1 open, 200 daily loss |
| Logs | `run/logs/api.log`, `run/logs/live.log` |

What it can prove: reconnects, memory over days, restarts, the backoff, the gate
refresh under real latency. What it cannot: fill quality, which is simulated and
optimistic — the whole order, immediately, at that price.

## II.18 ADR-002 — the risk kernel

`docs/adr-002-risk-kernel.md`, accepted 2026-09-08. It closes the question
ADR-001 left open: having put order submission inside this process, where does
the authority to submit come from?

**The kernel runs here, in the order path.** `trading-core` sets policy and is
never consulted to place a trade — forced by the owner's constraint that a
`trading-core` outage must not stop trading, which rules out a synchronous check
before every order.

Three decisions:

* **Authority is pre-authorised and does not expire.** A TTL is an outage
  dependency wearing a schedule: set it to 24 hours and a 25-hour outage stops
  trading, which is the forbidden outcome arriving a day late. Revoke-only makes
  the failure mode explicit instead.
* **Revocation blocks new entries and permits exits**, exactly as the kill
  switch, a stale gate and the daily loss limit already do. An account that
  cannot shed risk is more dangerous than one that cannot take it on, and
  flattening on revoke would let an infrastructure event decide a trade.
* **The kill switch stays as Step 22 built it** — this service's Redis plus a
  file on the node's disk, `trading-core` welcome but never required.

The cost is stated rather than hidden: **a revocation issued while
`trading-core` is unreachable does not arrive**, and between the outage and its
recovery the kill switch is the only way to stop an account. There is no design
that has both that and "an outage must not stop trading".

Step 22 built the enforcement before this named it. What remains is the mandate
itself — schema, revocation path, and a node that refuses to start without one.
Six conditions, none met, listed in the ADR.

## II.19 Step 29 — The mandate, and a kill switch that meant the opposite

### The docs said the opposite of the code, for a week

`evaluate` checks `kill_engaged` **before** the `reduce_only` exemption, so an
engaged kill switch rejects closing orders too. `.env.example`, the systemd
README and ADR-002 — committed the same day — all said exits were allowed.

The repo owner confirmed the code: **a kill switch is a total stop.** You reach
for one when you do not trust the strategy, and a strategy you do not trust
should not be closing positions either — its idea of an exit may be the bug. The
position becomes the operator's to close at the exchange, which is a real cost
and precisely why this is a separate instrument from the limits.

Every other brake — a stale gate, the daily loss limit, a revoked mandate —
blocks new entries and lets a position be shed. The kill switch is the one
deliberate exception, and there is now a test saying so, because three documents
drifted from four lines of code and nothing caught it.

### The mandate

ADR-002's remaining work: `engine.live.mandate`, plus
`PUT/GET/DELETE /v1/live/{accountId}/mandate`.

| Decision | Why |
|---|---|
| Carries its own limits | One source. Two copies that can disagree is how an account trades inside a limit nobody set |
| **No expiry field, asserted by a test** | A TTL is an outage dependency wearing a schedule. The test exists so nobody adds one back as a courtesy |
| Revocation annotates, never deletes | What was authorised, by whom, and when it was withdrawn all survive |
| A re-grant re-authorises | Rather than un-revoking, so the record of the withdrawal is not edited away |
| Live refuses without one | Absent is not permissive. "There was no record" is not a defence anyone wants to give |
| Simulation needs none | A mandate authorises money; a simulation has none. One is applied if present, so the path is exercised rather than dormant |

**Two failure modes deliberately pointing opposite ways.** An unreadable *kill
switch* counts as engaged — an operator who cannot be heard must not be assumed
to have said nothing. An unreadable *mandate* does **not** count as revoked —
authority already granted stands, because failing closed there would stop
trading on a Redis blip, which is the outcome ADR-002 exists to prevent.

### Deployment is verified rather than assumed

`docker compose build` produces `engine_server-api`, `-worker` and `-live`, 1.52
GB each. Until now every process had only ever run from the venv.

### Live remains gated

Two of ADR-001's seven conditions are open: **credentials from a secrets
manager** — there is nowhere safe to put a key, and no test that one cannot
reach a log or an HTTP response — and **the soak**, which needs time. Venue
readers stay stubs until a key exists to exercise them.

## II.20 Step 30 — Everything buildable before a key

Working through the pre-live list. What could be built without an exchange key
was built; what could not is named rather than faked.

### Credentials (ADR-001 condition 2)

`SecretsFileResolver` reads a key pair from a file mounted at runtime, and
**refuses one readable beyond its owner** — a world-readable secret is not a
secret, and a mode that permissive usually means it was written by something
that did not know it was handling a key.

Deliberately **not a cloud SDK**. The ADR's requirement is about where a key
must not be — not the image, not an environment variable, not the repo — and
every secrets manager worth using already projects onto a filesystem: a
Kubernetes `Secret` volume, `docker secret`, systemd `LoadCredential=`, Vault's
CSI driver. Binding to one vendor would add a cloud dependency to node startup
and buy nothing. `CredentialResolver` stays a protocol for the case where a
manager only offers an API.

`assert_usable_in_live` **refuses** the environment resolver rather than
discouraging it. "Development only" in a docstring is a comment; this is a rule.

### The key never reaches a log (ADR-001, same condition)

The ADR said "the structured logger already redacts nothing by default; that
changes". It has changed: any field whose *name* looks like a secret has its
value replaced, ambient `log_context` included. Name-based and blunt on purpose
— a value-based check cannot work, because an API key is an opaque string and so
is half of everything else logged.

Twenty-four tests, all asserting on the key *string* rather than on a code path,
because the path that leaks it will be one nobody thought to test. Including the
subtle one: **a malformed credential file must not quote itself into the error**,
since a JSON decode error prints the document it failed on and that document is
the key.

### Venue readers (ADR-001 condition 4, made real)

`engine.live.readers` implements both halves of what reconciliation compares.
Free and locked balances summed — a balance behind an open order is still the
account's, and reading only `free` would make the venue look poorer than the
cache and halt the node. Dust filtered, so a fraction of a cent cannot refuse a
start. `Decimal` throughout (rule 4).

**Building it found D21**, which would have halted every account on its first
live start.

**It has still never spoken to Binance**, and the tests say so in their own
docstring. A green run here means "correctly shaped", not "reconciliation
works" — and D21 is the argument for taking that distinction seriously.

### Audit and the runbook (ADR-002 conditions 5 and 6)

`mandate_id` is on every block, so "why did this order not go" is one log line
rather than two services' records joined on a timestamp.

`docs/runbook-live.md` covers the three different ways to stop an account and
why choosing wrongly under pressure matters, `HALTED` and how to clear it, and
the trade-off ADR-002 asked be written where operators read it: **during a
`trading-core` outage the kill switch is the only way to stop an account.**

### Where that leaves live

| | Met |
|---|---|
| ADR-001's seven conditions | **6 of 7** — open: the soak |
| ADR-002's six conditions | **6 of 6** |

Condition 2 is met in code and unmet in deployment: the resolver exists and
refuses the wrong things, and nothing has resolved a real key.

**The next step is one live start with `LiveNotPermitted` still in place.**
Reconciliation runs against the real exchange and then refuses to trade — the
first honest test of the venue reader, risking nothing.

