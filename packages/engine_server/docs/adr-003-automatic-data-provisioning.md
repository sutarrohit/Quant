# ADR-003 — The catalog fills itself

**Status:** accepted
**Date:** 2026-09-18
**Supersedes:** the manual-ingest precondition in spec section 4 and the
submit-time catalog check in section 7.2.

## The problem

A user with a strategy for SOL could not run it. The catalog held what somebody
had ingested by hand, the validator rejected any symbol that was not in it, and
the fix was a CLI invocation with six flags that the user had no way to know was
required:

```
POST /v1/backtests  ->  422  SYMBOL_NOT_IN_CATALOG
```

Nothing about that step needed a human. The request already names the
instrument, the timeframe and the window. The system knew exactly what was
missing and refused to get it.

## The decision

**The worker fetches whatever the catalog lacks, before the run.** Submitting a
backtest is the only thing a user does.

Three things had to move:

| Where | Was | Is |
|---|---|---|
| `worker/tasks.py` | run | provision, then run |
| `dsl/validator.py` caller | "is it in the catalog" | "is it in the catalog **or** listed at the venue" |
| `store/jobs.py` | QUEUED → RUNNING | QUEUED → FETCHING_DATA → RUNNING |

`data/provision.py` is the new step and is deliberately thin.
`Catalog.missing_intervals` already computed the gaps and `ingest()` already
fetched only those, recorded raw before transforming, and ran the quality
monitors. None of that is re-implemented.

## Why the worker, and not the handler

A cold two-year 1m window is minutes of paging against the venue. Doing that in
`submit` would hold an HTTP connection open for minutes and block the event
loop — the same reason the handler has never run a backtest (spec 7.1, rule 3).

The handler still answers *fast* questions. "Is this symbol real" is one of
them: one `exchangeInfo` call, cached in Redis, only for symbols the catalog
misses, with a one-attempt/3-second budget rather than ingest's patient retry.
A typo should still come back as a `422` on submit rather than as a job that is
accepted, queued, picked up, and then failed.

## Why an unreachable venue is permissive

If the venue cannot be reached during that check, the symbol is treated as
knowable and the job proceeds. The worker will fail it with an upstream code if
the outage persists.

The alternative is telling a user that their symbol does not exist because
Binance is down. That is false, and it is the kind of false that costs somebody
an afternoon.

## Why a short window is an error, not a shrink

`SOLUSDT` listed in 2020. A request starting in 2018 could be run over what
exists and reported with the real range attached. It is not:

> A backtest quietly run over two years when seven were requested is a result
> the caller will read as seven, and no amount of metadata further down makes
> that safe.

`DATA_RANGE_UNAVAILABLE` names the earliest date the venue has, so the fix is
one edit to the request. A shortfall of **one bar** at either end is tolerated,
because a window ending *now* cannot contain a bar that has not closed yet.

## What this does not change

**Determinism (rule 6) is intact.** Ingest is idempotent: a window already held
is a no-op, raw responses are append-only, and re-ingesting fetches only gaps.
The first run of a window defines the data; every later run reads the same bars
off disk. What changed is *when* the fetch happens, not whether the result is
stable.

The honest caveat: the first run of a never-before-seen window now depends on
what the venue serves at that moment. That was equally true when a human ran
`ingest` the day before — the dependency moved, it did not appear.

**The ingest CLI stays.** It is no longer a precondition, but it is still the
way to pre-warm a catalog deliberately, to backfill a delisted symbol, and to
ingest from a source that is not a live venue (`csv_file`).

## Consequences

- A new job status, `FETCHING_DATA`. The TypeScript caller branches on status,
  so this is a contract change; the status set is asserted by a test.
- Three new error codes: `SYMBOL_UNKNOWN_AT_VENUE`, `VENUE_UNSUPPORTED`,
  `DATA_RANGE_UNAVAILABLE`.
- A first backtest for a cold symbol is slow in a way the second is not. The
  status makes that legible rather than mysterious.
- `SOURCES` in `provision.py` is the list of venues that can self-provision.
  Today it is Binance spot. A venue absent from it produces
  `VENUE_UNSUPPORTED` naming the venue, never "no data for your symbol".
- **Unit tests must not reach a venue.** `tests/worker/conftest.py` stubs
  `ensure_window` for every worker test. Without it the suite downloads a month
  of bars into the developer's own `./catalog` the first time it runs — which
  is exactly what happened while building this.
