# CLAUDE.md

Guidance for Claude Code (and any coding agent) working in this repository.

## What this is

A thin FastAPI service around the **NautilusTrader** library. It holds market
data, runs backtests, and — from Phase 5 — runs live strategies that emit trade
*intents*. It is one service in a larger platform; the TypeScript `api-control`
and `trading-core` services own the ledger, risk kernel and OMS.

**Read `docs/nautilus-service-spec.md` before changing anything.** Part I is the
contract, Part II is the step-by-step build plan. Where they disagree, Part I
wins. That file is the source of truth; this one is a summary of the traps.

## Working agreement

- **One step per session.** Part II of the spec is a numbered ladder. Build one
  step, make its tests green, stop, and wait for the repo owner's review before
  starting the next. Do not run ahead.
- **Ask before starting a new phase.** Beginning a phase is the repo owner's
  call, not the agent's. Finish the current phase, report its acceptance
  result, and wait to be told to start the next one. Steps *within* an
  already-started phase still follow the one-step-per-session rule above.
- **Commit only when asked.** No `git commit`, no branch, no PR, until the repo
  owner explicitly asks for one. When they do, commit only the work they named
  and leave unrelated work in progress untracked.
- **Phase acceptance tests are gates.** A phase's acceptance step must be green
  before the next phase's first step begins. A phase whose tests cannot be made
  green is a design problem to surface, not a step to skip.
- **Record API deviations.** Where the installed NautilusTrader differs from the
  spec's assumed API, the installed version wins — and the deviation goes in
  `docs/nautilus-api-notes.md` in the same step that found it.

## Explaining things

When the repo owner asks a question — "what is X", "why X", "what's next" —
the answer is a **formatted document, not a wall of prose**.

- **Lead with the answer.** One or two sentences that actually answer it, then
  the supporting detail. Never bury the conclusion at the bottom.
- **Bullets over paragraphs.** A paragraph running longer than three lines is
  almost always a list that has not been broken up yet.
- **Tables when there are two dimensions** — component/owner, option/trade-off,
  phase/deliverable, setting/purpose.
- **Bold the load-bearing term** in each bullet, so the shape can be scanned
  without reading every word.
- **Short sentences, plain words.** If a sentence needs re-reading, split it.
- **Backticks on every** file path, command, setting, type and code symbol.
- **Headings once an answer passes roughly ten lines.** Below that they are
  noise.
- **Show the real output** — command results, error text, response bodies —
  rather than describing what it said.

Match length to the question. A one-line question gets a short answer, not an
essay with headings. The goal is that the answer is understood on one read.

## Rules that must not be broken

1. **No generated strategy code.** There is exactly one strategy class,
   `DslStrategy`, which receives the spec as a dict and interprets it at runtime.
   No `exec`, no `eval`, no emitting `.py` files. Reasons, in order: no untrusted
   code in a process that will later hold exchange credentials; the identical
   class runs in backtest and live so they cannot drift; specs stay as
   versionable, hashable data. If you are writing a code generator, you are on
   the wrong branch — stop.
2. **No PostgreSQL. In any phase.** No SQLAlchemy, no Alembic, no asyncpg, no
   `NT_DATABASE_URL`. Two services writing the same financial tables is how a
   fill exists in one schema and not the other. This service POSTs its results to
   `api-control` and lets it own the table.
3. **The HTTP handler never runs a backtest.** It validates synchronously and
   enqueues. A backtest pins a CPU for minutes; running one in the request
   handler blocks the event loop and kills the service under two users.
4. **`Decimal` for money, from strings, end to end.** Prices, quantities,
   notionals, fees, balances. `float` appears only inside indicator math.
   Float money is silent, cumulative, and unrecoverable once it is in a stored
   result.
5. **Fees and slippage are mandatory request inputs.** Never defaulted to zero.
   Omitted → `422`. A zero-cost backtest is a marketing number.
6. **Determinism.** Same spec + same data + same config → byte-identical results.
   No unseeded `random`, no `datetime.now()`, no dict-ordering or set-iteration
   dependence in any output path. There is a CI test asserting this across three
   runs; do not weaken it.
7. **No cache database in backtests.** In-memory cache only. A configured cache
   DB adds write latency to every event and introduces shared mutable external
   state, which breaks determinism. Required in live, forbidden here.
8. **Bar-close timestamps.** `ts_event` is the bar **close**, not the open.
   Exchange APIs return open time; the interval must be added. `ts_init ==
   ts_event` for historical ingest, and never `ts_init < ts_event`. This is the
   most common cause of a backtest that looks great and fails live.
9. **The interpreter never swallows errors.** An unknown indicator or operator
   raises. A broad `except` returning `False` turns a broken strategy into a
   silently inert one.
10. **No lookahead.** The evaluation context is built only from data at or before
    the current bar's close. Any access to a future bar is a bug, and there is a
    test designed to catch it.
11. **Fresh engine per backtest job.** Never reuse a `BacktestEngine` across
    runs; state leaks between them. `dispose()` explicitly after extraction —
    Nautilus engines hold a lot of memory and a leaking worker OOMs.
12. **Stable error codes.** Every failure returns a machine-readable `code`. The
    TypeScript caller branches on codes, never on message text. Tracebacks are
    persisted internally, never leaked in an HTTP response.
13. **Real-money trading is gated on ADR-001, and zero of its seven conditions
    are met.** `TradingMode.LIVE` raises `LiveNotPermitted`; `SIMULATION` is the
    only mode that runs. There is no setting that changes this, deliberately —
    a flag that could turn on real trading is a flag someone turns on by
    accident. The live cache must be a different Redis **instance** from arq,
    not a different logical DB (`DatabaseConfig` has no DB index — D15), and
    `flush_on_start` is never `True`. Both are asserted by tests.
14. **Do not build the intent bridge.** ADR-001 chose Option B: Nautilus submits
    orders to the venue directly and nothing else sends a live trade. Spec §11
    is dead and marked so. If something seems to need a `TradeIntent`, the
    question is whether Option B is still the decision — not whether to add the
    bridge back quietly.
15. **Unit tests never reach a venue.** `run_backtest` provisions missing data
    before running (ADR-003), so a test that exercises it with real settings
    downloads from Binance into the developer's own `./catalog`. That is what
    `tests/worker/conftest.py`'s `no_venue_calls` fixture is for; a test that
    wants the provisioning path patches `ensure_window` itself.
16. **A live node's failure mode is a process that looks fine.** Four separate
    defects (D17–D19) each produced a running, healthy-looking node that did
    nothing, or a stopped node that would not exit. None raised. Configuration
    tests cannot see any of them: the object graph is only assembled at
    `build()`. Anything touching node assembly needs a test that starts a real
    child and asks whether it is still there.

## Out of scope, deliberately

Real-venue execution · credential storage / KMS · approvals and the mandate's
authoring (TypeScript `trading-core`) · LLM calls or strategy authoring from
natural language · auth beyond the shared internal bearer token · any UI.

**The risk kernel is no longer out of scope.** ADR-002 moved it here: it runs in
the order path, in this process, because a `trading-core` outage must not stop
trading and a synchronous check would make it do exactly that. `trading-core`
still authors the mandate; this service enforces it.

## Stack

Python 3.13 · `uv` · `nautilus-trader==1.231.0` (pinned; verify import paths
against the installed version, not against memory) · FastAPI · Pydantic v2 +
`pydantic-settings` (`NT_` env prefix) · `arq` + Redis · `pandas` / `pyarrow` ·
`pytest` + `hypothesis` · `ruff` · `mypy --strict` over `dsl/`, `strategies/`,
`backtest/`.

## Commands

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy src
uv run fastapi dev src/engine/api/app.py --port 8000
uv run arq engine.worker.main.WorkerSettings
uv run python -m engine.live.main
uv run python -m engine.data.ingest --exchange binance --symbol BTCUSDT \
  --market spot --timeframe 15m --start 2023-01-01 --end 2025-01-01  # optional
```

Ingest is a pre-warm, not a precondition: the worker fetches whatever window a
backtest names and the catalog lacks (ADR-003).

## Conventions

- **Errors live in `src/engine/errors/`**, one file per area, named for the
  package that raises them (`errors/live.py` for `engine.live`). `base.py` holds
  `ErrorCode`, `EngineError` and the two response shapes. Import from the
  package -- `from engine.errors import NoDataForWindow` -- and add every new
  class to `__all__`. Codes are append-only: the TypeScript caller branches on
  them. See `docs/explanations/error-handling.md`.
- Package `engine`, `src/` layout. `strategy_path` strings look like
  `engine.strategies.dsl_strategy:DslStrategy` and end up embedded in stored
  configs — renaming the package later is expensive.
- Structured JSON logging with `job_id`, `strategy_version_id`, `spec_hash`,
  `request_id`. Spec bodies at DEBUG only; they get large.
- Adding an indicator = one entry in the `INDICATORS` registry plus one test.
  If it requires touching the interpreter, the abstraction is wrong.
- The `ImportableStrategyConfig` construction is shared by `backtest/builder.py`
  and (later) `live/node.py` through one function. If those two diverge, the
  platform's core guarantee is gone.
