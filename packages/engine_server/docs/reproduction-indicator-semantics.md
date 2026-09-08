# Reproduction: indicator semantics

**Phase 4, first pass.** Recorded 2026-09-08.

Spec §8 asks for a published backtest reproduced within tolerance, and says
that if the numbers miss, the data or the simulator is at fault and must be
fixed before anything downstream is built.

Before comparing against anyone else's numbers, this pass asked a narrower and
more answerable question: **does this engine compute what it says it computes?**
A published RSI strategy cannot be reproduced by an engine whose RSI is not
the RSI everyone else means, and no tolerance band would have revealed that —
the result would simply have been "close enough, near enough" while measuring
a different curve.

Two defects were found. Both were in the simulator, not the data.

---

## Finding 1 — the RSI was not Wilder's

`RelativeStrengthIndex(period)` takes an optional `ma_type` defaulting to
`EXPONENTIAL`. Every textbook, every published RSI strategy, and TradingView's
`RSI` mean **Wilder's** smoothing: `alpha = 1/n`, not `2/(n+1)`.

### Method

Wilder's RSI was written from its definition in plain Python — no Nautilus —
and compared bar for bar against the engine over 2,000 bars of BTCUSDT 15m.

| Configuration | Max difference vs the independent implementation |
|---|---|
| Nautilus default (`EXPONENTIAL`) | 12.94 RSI points |
| Textbook Wilder, seeded with the first observation | 34.84 points |
| **`MovingAverageType.WILDER`, unseeded** | **3.6 × 10⁻¹⁴** |

The last row is float rounding: the same recurrence accumulated in a different
order. Anything larger would mean one of the two is computing something else.

The seeding detail matters. Nautilus starts its average gain and loss at zero
and smooths in; it does not seed them with the first observation. A reference
implementation that seeds differs early and converges later, which is precisely
the shape of a bug that a tolerance band would absorb.

### Impact

A difference of up to 34 RSI points is the difference between *oversold* and
*overbought*. A spec reading `crossesAbove 30` was being evaluated against a
curve nobody else computes.

Six months of BTCUSDT 15m, same spec, same data, same costs:

| | Before (`EXPONENTIAL`) | After (Wilder) |
|---|---|---|
| trades | 107 | 73 |
| total return | −19.94% | −12.67% |
| Sharpe | −1.60 | −1.20 |

January 2024 alone moved from **−0.78% over 20 trades** to **+1.50% over 12**.
A losing month became a winning one on an indicator definition.

### Resolution

`dsl/indicators.py` passes `ma_type=MovingAverageType.WILDER`.
`tests/dsl/test_rsi_reference.py` holds the independent implementation and
fails if the two ever diverge by more than float epsilon. Recorded as D13.

---

## Finding 2 — orders fill at the signal bar's close

Spec §6 says "entries are submitted for the next bar". They are not: an order
submitted from `on_bar` fills at **that same bar's close**.

```
signal on bar closing 2024-01-01T04:00:00Z   C = 42330.49
fill                  2024-01-01T04:00:00Z  px = 42330.49    <- the signal bar's close
next bar open                                    42330.50    <- not this
```

This is **not lookahead** — the close was already observed when the decision was
made. It is optimistic in a different way: you cannot transact at the closing
print.

### Method

Rather than argue about it, the gap was measured across every bar in the
catalog.

| `\|open[t+1] − close[t]\|` as % of price | |
|---|---|
| identical | 49.1% of 70,170 bars |
| median | 0.000010% |
| p99 | 0.005517% |
| max | 0.454726% |

One round trip costs 30 bps — `0.300000%`. The median discrepancy is about
**30,000 times smaller than the costs already modelled**.

### Resolution

Left as-is, deliberately, and now documented rather than assumed. Crypto trades
continuously with no auction and no overnight gap, so there is nothing for the
assumption to hide. A market with real gaps — equities, with overnight moves —
must revisit this before any result is trusted, and that belongs with whoever
adds that market. Recorded as D12, with a test pinning the behaviour so it
cannot change silently.

---

## What this pass did not do

**It did not reproduce a third-party published result.** That still needs a
named target with published metrics, stated fees and a stated period — open
question Q1 in the plan's §II.6, which the spec leaves to the repo owner.

What it establishes is the precondition: an engine whose indicators are the
indicators their names claim, and whose fill assumption is measured rather than
believed. Comparing against a published number before that would have produced
a delta with two candidate explanations and no way to separate them.

## Numbers recorded elsewhere that predate this

§II.9's Phase 2 acceptance record (27 round trips over Jan–Feb 2024) was taken
with the pre-Wilder RSI. Its criteria still hold — round trips occur, three
runs are byte-identical, a never-triggering spec produces no orders — but the
specific trade counts in that record are from the old indicator. Both golden
files were regenerated deliberately, which is what a golden file is for.
