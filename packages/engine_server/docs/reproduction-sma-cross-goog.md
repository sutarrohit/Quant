# Reproduction: SMA crossover on GOOG, against backtesting.py

**Phase 4, spec §8.** Recorded 2026-09-08.

## Result

Running the same strategy on the same data through this service and through
`backtesting.py` 0.6.6:

| Metric | backtesting.py | this service | delta |
|---|---|---|---|
| trades | 46 | 46 | 0 |
| win rate | 52.1739% | 52.1739% | 0 |
| closed-trade profit | $41,753.20 | $41,753.18 | **$0.016** |
| final equity | $59,522.09 | $59,522.08 | **$0.01** |
| total return | 495.2209% | 495.2208% | **0.0001 pp** |

**Every closed trade agrees on quantity, entry price and exit price** — zero
divergence across all 46. The residual is rounding in commission arithmetic.

Two defects were found and fixed getting here, and one documented assumption
was finally priced.

## The target and why it changed

The intended benchmark was `backtesting.py`'s published example: GOOG daily,
2004-08-19 → 2013-03-01, SMA(10)×SMA(20), $10,000, 0.2% commission, published
**Return 718.12%, Sharpe 0.72, Equity Final $81,812.37**.

**That published figure does not reproduce.** Running their own documented
example through `backtesting.py` 0.6.6 gives **462.64%**, Sharpe **0.60**,
$56,263.52 — off by 255 percentage points. Buy & Hold Return
(`607.3703606212162`) and Exposure (`94.27374301675978`) match the published
values exactly; both are data-derived and independent of how orders fill. So
the data is identical and the engine's behaviour changed between versions.

Recorded separately in `reproduction-benchmark-search.md`. The consequence for
this document is that the reference is the **running engine**, not the
published number — which is stronger anyway, because a delta against a running
engine can be investigated rather than guessed at.

## Setup

| | |
|---|---|
| Data | GOOG daily, 2,148 bars, 2004-08-19 → 2013-03-01 |
| Ingested via | `CsvSource`, through the normal ingest path — raw recorded first, `ts_event` = bar close, quality monitors run |
| Strategy | `sma(10) crossesAbove sma(20)` to enter, `crossesBelow` to exit; long only on both sides |
| Cash | $10,000 |
| Commission | 20 bps, 0 slippage |

Three structural differences were named before running, not discovered as
mismatches:

1. **Fill timing.** `backtesting.py` fills at the next bar's open; this service
   fills at the signal bar's close (D12).
2. **Direction.** Their shipped example is long/short; this DSL is long-only,
   so a long-only variant was run on *both* sides.
3. **Final open position.** Their `finalize_trades` closes a position still
   open at the end of data; this service's metrics count closed trades only.

## Comparison

`trade_on_close=True` and `finalize_trades=False` set on the reference, which
makes differences 1 and 3 disappear:

| Metric | backtesting.py | this service | delta |
|---|---|---|---|
| trades | 46 | 46 | 0 |
| win rate | 52.1739% | 52.1739% | **0** |
| closed-trade PnL | $41,753.20 | $41,753.18 | **$0.016** |
| Sharpe | 0.8388 | 0.7943 | −0.0445 |
| Equity Final | $59,522.09 | $51,753.18 | −$7,768.91 |

Trade-by-trade, across all 46: **zero divergence** in quantity, entry price or
exit price. The first five, side by side:

```
their  Size 55  Entry 180.40  Exit 180.08  PnL   -57.25280
mine   qty  55  entry 180.40  exit 180.08  pnl   -57.25
their  Size 49  Entry 185.29  Exit 297.30  PnL  5441.19618
mine   qty  49  entry 185.29  exit 297.30  pnl  5441.19
```

## Explaining the two remaining differences

### Fill timing, priced

Toggling `trade_on_close` on the reference isolates D12 exactly:

| | next-open fills | on-close fills | this service |
|---|---|---|---|
| win rate | 61.70% | 53.19% | 52.17% |
| return | 525.62% | 490.41% | 417.53% |
| Sharpe | 0.8579 | 0.8354 | 0.7943 |

Filling at the signal bar's close costs **8.5 percentage points of win rate**
on this data and 35 points of return.

This is the number the crypto measurement could not produce. On BTCUSDT 15m,
`close[t]` equals `open[t+1]` on 49% of bars with a median difference of
0.00001%, so D12 was immaterial. **Daily equities gap overnight, and here the
assumption is worth real money.** D12's conclusion — harmless on a continuous
market, must be revisited on a gapping one — is now evidenced rather than
asserted.

### The final open position — fixed

Before the fix, the remaining $7,768.91 was the unrealized value of a position
still open on the last bar. `backtesting.py` marked it to market; this service's
equity curve was realized-only and simply ignored it.

That was a real limitation, and this benchmark priced it: **77.7 percentage
points of return** on this strategy, because a trend follower is usually
holding when the data runs out.

`summarise` now takes the unrealized value of any open position, marked to the
last bar's close, and reports it alongside a count of open positions. Ending
equity became $59,522.08 against the reference's $59,522.09.

The trade list still contains closed trades only, which is the honest split: a
position that has not closed has no realized profit, and saying otherwise would
be inventing one.

## Defects found

**Sizing did not reserve for its own commission.** `size_by_risk` capped the
quantity at `available / price`, so a strategy sizing near 100% of equity
bought an amount it could not also pay the fee on. Nautilus does not reject
such an order: it fills it, the balance goes negative, and the simulated
exchange **halts the entire backtest**:

```
2005-02-08 [ERROR] Stopping backtest from AccountBalanceNegative(balance=-10.57, currency=USD)
```

Three trades of forty-seven ran. The cap is now
`available / (price * (1 + cost_rate))`, with the rate carried on the strategy
config so sizing and charging cannot disagree.

The bug was invisible on crypto: at 1% risk with a 2% stop, a position is half
the balance and always had the headroom to hide it. It took a different market
and a different sizing regime to surface.

**A halted backtest reported SUCCEEDED — fixed.** The run above returned three
trades and a summary with no indication it had stopped in 2005 rather than
2013. Same shape as D10: a broken run indistinguishable from a legitimate one.

The strategy already counted the bars it saw, so the check is exact rather than
a heuristic about when trading stopped — a strategy may legitimately go quiet
for years. The runner now compares that count against the catalog's bar count
for the window and raises `BACKTEST_INCOMPLETE`:

```
BACKTEST_INCOMPLETE — the engine stopped after 119 of 2148 bars;
the run was halted rather than completed
```

## Verdict

The two engines agree. Closed-trade profit differs by **1.6 cents on $41,753**
and final equity by **1 cent on $59,522** — rounding in the commission
arithmetic, on runs that take the same 46 trades at the same sizes and prices.

The one remaining difference is deliberate and configured, not tolerated: this
service fills at the signal bar's close and the reference fills at the next
bar's open, so the reference is run with `trade_on_close=True`. That difference
is now measured rather than assumed — on this data it is worth 8.5 percentage
points of win rate, against effectively nothing on continuous crypto.

§8 is satisfied: the deltas are explained rather than reported, and the two
that were errors have been fixed.

`tests/reproduction/test_cross_engine.py` runs this comparison as a test, so a
future change that breaks the agreement fails rather than drifts. To run it by
hand and read the output:

```bash
uv run python scripts/compare_engines.py               # the comparison
uv run python scripts/compare_engines.py --trades      # trade by trade
uv run python scripts/compare_engines.py --fill-study  # what fill timing costs
```

The reference series is ingested on first run, through the normal ingest path.

## One metric that differs by design: Sharpe

Sharpe is 0.8388 against 0.7943 — and unlike the others, this one is not
rounding.

Risk statistics come from the *shape* of the equity curve, not its endpoints.
This service's curve is realized: it steps when a trade closes and is flat in
between. The reference marks the open position every day, so its curve moves on
days when ours does not. Same start, same end, different path — so the
volatility of the daily returns differs, and Sharpe with it. Maximum drawdown
has the same cause.

Neither is wrong; they answer slightly different questions, and total return is
unaffected because it depends only on the endpoints. A mark-to-market curve
would make them comparable, and needs a portfolio valuation per bar, which is
not built. The comparison script separates the metrics that must agree from
this one, rather than hiding it inside a tolerance.
