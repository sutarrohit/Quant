# Engine Server — NautilusTrader service

A thin Python service around [NautilusTrader](https://nautilustrader.io). It does
exactly three things:

1. **Holds market data** — a Parquet catalog of bars and instrument definitions.
2. **Runs backtests** — submitted over HTTP, executed on a queue worker.
3. **(Phase 5+) Runs live strategies** that emit trade *intents*, never orders.

NautilusTrader is a library, not a daemon. There is nothing to install and run;
this repo *is* the server around it.

The full contract and the step-by-step build plan live in
[`docs/nautilus-service-spec.md`](docs/nautilus-service-spec.md). Read it before
changing anything here.

## The rules that are not negotiable

- **Strategies are never generated as Python source.** There is one strategy
  class, `DslStrategy`, which interprets a spec dict at runtime. No `exec`, no
  `eval`, no code generation — the same class runs in backtest and live, so
  simulation and production cannot drift.
- **This service never connects to the platform PostgreSQL.** Ledger, orders,
  fills, mandates and audit belong to the TypeScript `api-control` /
  `trading-core`. One writer per table. Python proposes; TypeScript records.
- **The HTTP handler never runs a backtest.** It validates and enqueues. A
  backtest pins a CPU for minutes.
- **`Decimal` for money, end to end.** `float` appears only inside indicator
  math.
- **Fees and slippage are mandatory inputs.** A zero-cost backtest is a
  marketing number, not a result.
- **The catalog fills itself.** A backtest names an instrument, a timeframe and
  a window; the worker fetches whatever of that the catalog does not hold, and
  the user runs no ingest command (ADR-003). Fetching only *gaps* is what keeps
  this from weakening the rule below.
- **Same spec + same data + same config → identical results.** There is a CI
  test for this. Do not weaken it.

## Status

**Phase 5 is closed** — the data catalog, the DSL, `DslStrategy`, the backtest
job service, the reproduction milestone and the live runtime are all built. The
step ladder's acceptance records run through Step 30 in Part II of the spec.

**Live trading does not run.** `TradingMode.LIVE` raises `LiveNotPermitted`
(HTTP 409) until the seven conditions in
[`docs/adr-001-live-execution.md`](docs/adr-001-live-execution.md) are met, and
they are not. There is no setting that overrides this — it is a gate in
`engine/live/node.py`, not a feature flag. `SIMULATION` is the mode that runs.

Progress is tracked as the step ladder in Part II of the spec. Each step is
built, reviewed, and only then followed by the next.

## Requirements

- Python 3.13
- [uv](https://docs.astral.sh/uv/)
- **Two Redis instances** — see below. Separate *instances*, not separate
  database indices.

This service needs **no PostgreSQL**. That is a rule, not an omission.

## The two Redis instances

| Port | Holds | Needed for |
|---|---|---|
| 6379 (`NT_REDIS_URL`) | arq job queue, live desired/observed state | everything |
| 6380 (`NT_CACHE_REDIS_URL`) | Nautilus's cache: open orders and positions | simulation and live |

They must be different **servers**. Nautilus's `DatabaseConfig` exposes host and
port and nothing else (`docs/nautilus-api-notes.md` D15), so a trailing `/1`
never reaches it and both would land on database 0 of one instance — where a
`FLUSHDB` aimed at the job queue would erase live position state. The node
checks this at startup and refuses to boot if it is violated.

### Starting them with Docker

One container each. Named, so the second one is obviously not the first:

```bash
# Queue + live desired state. Needed for everything.
docker run -d --name engine-redis-queue \
  -p 6379:6379 -v engine-redis-queue:/data \
  redis:7-alpine redis-server --appendonly yes

# Nautilus's live cache. Only needed for simulation and live.
docker run -d --name engine-redis-cache \
  -p 6380:6379 -v engine-redis-cache:/data \
  redis:7-alpine redis-server --appendonly yes
```

The cache container maps **host 6380 to container 6379** — Redis always listens
on 6379 inside its own container, and the host port is what keeps the two
instances apart.

`--appendonly yes` on both, and a named volume on both, because the cache is the
state a live restart recovers from. A cache that does not survive a container
restart has open positions the node cannot reconcile against.

Day to day:

```bash
docker start engine-redis-queue engine-redis-cache
docker stop  engine-redis-queue engine-redis-cache
docker logs -f engine-redis-queue
docker exec -it engine-redis-queue redis-cli ping     # -> PONG
```

To throw the queue away without touching live state — the operation the two
instances exist to make safe:

```bash
docker exec engine-redis-queue redis-cli FLUSHDB
```

`docker compose up` further down starts both of these for you, wired to the app
containers. These commands are for running Redis in Docker while the API and
worker run on the host with `uv`.

## Getting started

```bash
uv sync
cp .env.example .env        # then set NT_INTERNAL_API_KEY
uv run pytest
```

Settings are read by `pydantic-settings` from the environment with the `NT_`
prefix. There is deliberately no `NT_DATABASE_URL`.

## Running it

There is no single "start the server" command, because the service is
deliberately more than one process. Five, at most:

| # | Process | Command |
|---|---|---|
| 1 | Queue Redis | `redis-server --port 6379 --daemonize yes` |
| 2 | Cache Redis | `redis-server --port 6380 --daemonize yes` |
| 3 | API | `uv run fastapi dev src/engine/api/app.py --port 8000` |
| 4 | Backtest worker | `uv run arq engine.worker.main.WorkerSettings` |
| 5 | Live supervisor | `uv run python -m engine.live.main` |

Processes 1 and 2 can equally be containers — see
[Starting them with Docker](#starting-them-with-docker) above, which is the
better option if you would rather not install Redis on the host.

Which ones you need depends on what you are doing:

| Goal | Processes |
|---|---|
| **Backtests** | 1, 3, 4 |
| **Simulation** (paper) | 1, 2, 3, 5 |
| **Live** | 1, 2, 3, 5 — and it will 409 |

The mode is **a field in the request**, not a different process. `PUT
/v1/live/{account_id}` with `"mode": "SIMULATION"` or `"mode": "LIVE"` is the
whole difference; the same supervisor and the same `DslStrategy` run both.
"Sandbox" and "paper" are the industry's words for `SIMULATION` — the code says
`SIMULATION` everywhere, because three names for one thing is how a node ends
up declaring itself live while running a simulated exchange (D17).

All of it at once, in one terminal:

```bash
./scripts/dev.sh           # redis x2 + api + worker
./scripts/dev.sh --live    # and the live supervisor
```

Or in containers, which also wires both Redis instances for you:

```bash
docker compose up --build
```

**The API alone computes nothing.** `POST /v1/backtests` validates and enqueues;
without process 4 the job sits in Redis forever. Likewise `PUT /v1/live/...`
records a desire — process 5 is what converges on it. That split is the point:
restarting the API changes nothing about what is trading.

## Market data

**You do not ingest anything first.** Submit a backtest for a symbol nobody has
ever fetched and the worker downloads what it needs before running:

```
QUEUED  ->  FETCHING_DATA  ->  RUNNING  ->  SUCCEEDED
```

The first run of a cold window is slow — a two-year 1m window is minutes of
paging against the venue. Every run after it reads Parquet off disk, because
only *missing* ranges are ever fetched.

Three ways it says no, each naming the fix:

| Code | Means |
|---|---|
| `SYMBOL_NOT_IN_CATALOG` (422 on submit) | The venue does not list that symbol. A typo, caught before the job exists. |
| `VENUE_UNSUPPORTED` | No data source for that venue. Today the list is Binance spot. |
| `DATA_RANGE_UNAVAILABLE` | The venue has no history that far back. The error carries the earliest date it does have. |

A short window is refused rather than quietly shrunk: a run over two years when
seven were asked for is a number the caller will read as seven.

`engine.data.ingest` still exists and is still the way to **pre-warm** a catalog
deliberately, backfill a delisted symbol, or load from a CSV rather than a live
venue. It is no longer something anyone has to run first.

## Endpoints

| Route | Does |
|---|---|
| `GET /health`, `GET /ready` | Liveness and readiness |
| `POST /v1/backtests` | Validate and enqueue a run |
| `GET`/`DELETE /v1/backtests/{job_id}` | Poll status and result; cancel |
| `GET /v1/catalog/instruments` | What the catalog holds |
| `PUT`/`GET`/`DELETE /v1/live/{account_id}` | The desired state of an account |
| `POST`/`GET`/`DELETE /v1/live/{account_id}/kill` | The kill switch, over HTTP |
| `PUT`/`GET`/`DELETE /v1/live/{account_id}/mandate` | The account's mandate |

Every route needs the `NT_INTERNAL_API_KEY` bearer token. The API refuses to
start without one rather than serve unauthenticated.

There is also an **on-disk kill switch** that works when Redis and the API do
not, which is exactly when you are most likely to want it:

```bash
touch run/kill/kill-acct_1      # one account
touch run/kill/kill-all         # everything
```

It is a *total* stop — exits included. See
[`docs/runbook-live.md`](docs/runbook-live.md) before using it in anger.

## Layout

```
src/engine/
  api/          FastAPI app, routes, auth, dependencies
  dsl/          strategy spec schema, validator, interpreter, indicator registry
  strategies/   dsl_strategy.py -- the ONE strategy class
  backtest/     builder (pure), runner, queue, result metrics
  data/         catalog access, exchange ingest, quality monitors
  worker/       arq worker entrypoint and tasks
  store/        job records (Redis), result artifacts (Parquet)
  live/         supervisor, node, reconciliation, kill switch, risk, mandates
  simulation/   live feed, simulated fills -- Nautilus's `sandbox` environment
deploy/systemd/ unit files for a non-container deployment
docs/           spec, Nautilus API notes, ADRs, runbook, reproduction reports
scripts/        dev.sh, compare_engines.py
tests/
```

## Commands

| Command | Does |
|---|---|
| `./scripts/dev.sh [--live]` | Everything above, in one terminal |
| `uv run fastapi dev src/engine/api/app.py` | API locally, with reload (`fastapi run` in production) |
| `uv run arq engine.worker.main.WorkerSettings` | The backtest worker |
| `uv run python -m engine.live.main` | The live/simulation supervisor |
| `uv run python -m engine.data.ingest --exchange binance --symbol BTCUSDT --market spot --timeframe 15m --start 2023-01-01 --end 2025-01-01` | Pre-warm the catalog. Optional — a backtest fetches what it needs (ADR-003) |
| `uv run pytest` | Tests |
| `uv run ruff check .` | Lint |
| `uv run mypy src` | Types |
| `uv run python scripts/compare_engines.py` | Compare this engine against `backtesting.py` |
