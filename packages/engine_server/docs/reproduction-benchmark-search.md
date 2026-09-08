# Finding a published benchmark

**Phase 4.** Recorded 2026-09-08.

Spec §8 asks for "a strategy with published, reproducible results". This
records the search, because the result of it is itself a finding.

## The candidate

`backtesting.py` is a widely used Python backtesting library whose front-page
example is a moving-average crossover with a complete, published result. It is
better specified than most:

| | |
|---|---|
| Data | GOOG daily, 2004-08-19 → 2013-03-01, shipped with the library |
| Strategy | SMA(10) × SMA(20) crossover, long and short |
| Cash | $10,000 |
| Commission | 0.2% |

Published metrics: **Return 718.12%**, Equity Final **$81,812.37**, Sharpe
**0.72**, Sortino **1.44**, Buy & Hold Return **607.37%**, Exposure **94.27%**.

Everything §8 asks for — stated data, stated fees, stated period, stated
strategy — and the reference engine is installable, so the number can be
checked rather than trusted.

## It does not reproduce

Running that exact example, with that exact data, through `backtesting.py`
**0.6.6**:

| Metric | Published | backtesting.py 0.6.6 | Delta |
|---|---|---|---|
| Return | 718.12% | **462.64%** | −255 pp |
| Equity Final | $81,812.37 | **$56,263.52** | −$25,549 |
| Sharpe | 0.72 | **0.60** | −0.12 |
| Sortino | 1.44 | **1.15** | −0.29 |
| Buy & Hold Return | 607.37% | 607.3703606212162 | **exact** |
| Exposure Time | 94.27% | 94.27374301675978 | **exact** |

The two data-derived metrics match to every digit available. Buy & Hold is
`last_close / first_close − 1`, and exposure is a count of bars in position;
neither depends on how the engine fills orders. So **the data is identical and
the engine's behaviour changed**.

The published figure was produced by an earlier version. Which one, and what
changed, is `backtesting.py`'s business rather than ours — the point for this
project is narrower and sharper:

> A published backtest result, from a well-maintained library, complete with
> stated data and fees, is off by 255 percentage points against the current
> version of the very library that published it.

That is what §8 is defending against, demonstrated on the first candidate
examined. It also means a published number needs one more thing nobody states:
**the version of the engine that produced it.**

## What this changes about the target

The published *number* cannot be the benchmark. The published *engine* still
can: `backtesting.py` 0.6.6 is a real, independent, widely used implementation
that can be run on demand, and comparing against a running engine is stronger
than comparing against a page — every delta can be investigated rather than
guessed at.

The plan is therefore a cross-engine reproduction: the same strategy, the same
data, run through `backtesting.py` and through this service, with each
structural difference enumerated in advance rather than discovered as a
mismatch.

Three are known already:

1. **Fill timing.** `backtesting.py` fills at the next bar's open; this service
   fills at the signal bar's close (D12). On BTCUSDT 15m that was measured as
   immaterial — 49% of bars have `close[t] == open[t+1]`. On daily equities it
   will not be, because there are overnight gaps. This benchmark should
   quantify what D12 costs on a market that actually gaps.
2. **Sizing.** `backtesting.py` buys with all available cash; this service
   sizes from a risk budget.
3. **Direction.** Their example goes long and short; this DSL is long-only, so
   the comparison must use a long-only variant on both sides.

Each is a named assumption, which is what makes a delta explainable rather than
merely reported.

## Prerequisite

The data is GOOG daily. Ingest currently speaks only to Binance, so this needs
a second `MarketDataSource` — which the protocol was introduced for in Step 3
precisely so that a new source is a new module rather than an edit to
`ingest.py`.
