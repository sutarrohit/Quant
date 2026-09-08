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
- **Same spec + same data + same config → identical results.** There is a CI
  test for this. Do not weaken it.

## Status

**Step 0 of 18 complete** — the FastAPI blog template this repo started from has
been removed, and the project is configured for the service described in the
spec. No domain code exists yet.

Progress is tracked as the step ladder in Part II of the spec. Each step is
built, reviewed, and only then followed by the next.

## Requirements

- Python 3.13
- [uv](https://docs.astral.sh/uv/)
- Redis (from Phase 3)

## Getting started

```bash
uv sync
cp .env.example .env        # then set NT_INTERNAL_API_KEY
uv run pytest
```

Settings are read by `pydantic-settings` from the environment with the `NT_`
prefix. There is deliberately no `NT_DATABASE_URL`.

## Layout

```
src/engine/
  api/          FastAPI app, routes, dependencies
  dsl/          strategy spec schema, validator, interpreter, indicator registry
  strategies/   dsl_strategy.py -- the ONE strategy class
  backtest/     builder (pure), runner, result metrics
  data/         catalog access, exchange ingest, quality monitors
  worker/       arq worker entrypoint and tasks
  store/        job records (Redis), result artifacts (Parquet)
  live/         Phase 5+ -- does not exist until ADR-001 is written
docs/           spec, Nautilus API notes, ADRs, reproduction reports
tests/
```

## Commands

| Command | Does |
|---|---|
| `uv run fastapi dev src/engine/api/app.py` | Run the API locally |
| `uv run arq engine.worker.main.WorkerSettings` | Run the backtest worker |
| `uv run python -m engine.data.ingest ...` | Ingest exchange data into the catalog |
| `uv run pytest` | Tests |
| `uv run ruff check .` | Lint |
| `uv run mypy src` | Types |
| `uv run python scripts/compare_engines.py` | Compare this engine against `backtesting.py` |
