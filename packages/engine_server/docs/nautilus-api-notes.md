# NautilusTrader API notes

Where `docs/nautilus-service-spec.md` and the installed NautilusTrader disagree,
**the installed version wins** (spec §2). This file records every such deviation,
with the version it was observed against.

**Installed version: `1.231.0`** (pinned in `pyproject.toml`), Python 3.13.15.

Verify after any version bump:

```bash
uv run python -c "import nautilus_trader; print(nautilus_trader.__version__)"
```

Docs for the installed version: <https://nautilustrader.io/docs/>

---

## Confirmed import paths

Checked by import against 1.231.0 on 2026-09-04. Every path in spec §2 exists.

| Symbol | Module |
|---|---|
| `BacktestNode` | `nautilus_trader.backtest.node` |
| `BacktestRunConfig`, `BacktestDataConfig`, `BacktestVenueConfig`, `BacktestEngineConfig` | `nautilus_trader.backtest.config` |
| `ImportableStrategyConfig`, `StrategyConfig`, `LoggingConfig` | `nautilus_trader.config` |
| `CacheConfig`, `DatabaseConfig`, `MessageBusConfig`, `TradingNodeConfig` | `nautilus_trader.config` |
| `ParquetDataCatalog` | `nautilus_trader.persistence.catalog` |
| `Strategy` | `nautilus_trader.trading.strategy` |
| `Bar`, `BarType`, `InstrumentId`, `Quantity`, `Price` | `nautilus_trader.model` |
| `TradingNode` | `nautilus_trader.live.node` |

The four backtest config classes are **also** re-exported from
`nautilus_trader.backtest.node`, which is what spec §2 imports them from. Both
work. Prefer `nautilus_trader.backtest.config` — it is where they are defined,
and a re-export is likelier to move than a definition.

---

## Deviations

### D1 — Indicators have no per-indicator submodules

**Observed:** 1.231.0 · **Affects:** spec §5.4, `dsl/indicators.py` (Step 7)

Spec §5.4 implies module paths such as `nautilus_trader.indicators.rsi`,
`nautilus_trader.indicators.average.sma` and `nautilus_trader.indicators.atr`.
**None of these exist.** There is no `nautilus_trader.indicators.average`
subpackage at all.

Indicators are exported flat from `nautilus_trader.indicators`:

```python
from nautilus_trader.indicators import (
    AverageTrueRange,
    ExponentialMovingAverage,
    RelativeStrengthIndex,
    SimpleMovingAverage,
)
```

The internal subpackages that do exist are grouped by category, not by
indicator: `averages`, `momentum`, `trend`, `volatility`, `volume`, `base`,
`spread_analyzer`, `fuzzy_candlesticks`. Import from the top-level
`nautilus_trader.indicators` namespace rather than reaching into these.

Roughly 45 indicators are exported, including `RelativeStrengthIndex`,
`SimpleMovingAverage`, `ExponentialMovingAverage`, `AverageTrueRange`,
`BollingerBands`, `MovingAverageConvergenceDivergence`, `DonchianChannel`,
`KeltnerChannel`, `Stochastics`, `OnBalanceVolume`,
`VolumeWeightedAveragePrice`. This comfortably covers the Step 7 registry
(`rsi`, `sma`, `ema`, `atr`, plus `volume` read from the bar itself).

No impact on the DSL: indicator names in a spec are ours, and the registry is
the only place that touches a Nautilus import.

---

### D2 — `ParquetDataCatalog` construction and query shapes

**Observed:** 1.231.0 · **Affects:** spec §4.1, §4.4, `data/catalog.py` (Step 2)

Four things the spec does not say, all verified by round-trip against 1.231.0.

**Use `from_uri`, not the constructor.** `ParquetDataCatalog(path, fs_protocol=...)`
takes a path *plus* a protocol, so passing `s3://bucket/catalog` as `path`
produces a broken catalog rather than an error. `ParquetDataCatalog.from_uri(uri)`
parses the URI into path + protocol, and resolves a bare relative path to an
absolute `file://` URI. `NT_CATALOG_PATH` may be either, so `from_uri` is the
only correct entry point.

**`bars()` takes strings, not `BarType` objects.**

```python
def bars(self, bar_types: list[str] | None = None,
         instrument_ids: list[str] | None = None, **kwargs) -> list[Bar]:
    return self.query(data_cls=Bar, identifiers=(bar_types or instrument_ids), **kwargs)
```

`start` and `end` are not named parameters — they reach `query()` through
`**kwargs`. They accept UTC nanoseconds and are **inclusive at both ends**
(a query from bar 100 to bar 149 returns 50 bars).

**There is no API that enumerates bar types.** `list_data_types()` returns
data-class names (`['bar', 'currency_pair']`), not identifiers.
`get_intervals(Bar, None)` returns only one bar type's intervals, not all of
them. Bar types must be derived from the catalog's file layout, which is
`<root>/data/bar/<bar_type>/<start>_<end>.parquet` — see `Catalog.bar_types`.

**Absent identifiers return empty, not errors.** `get_intervals` returns `[]`,
`query_first_timestamp` returns `None`, `bars()` returns `[]`.

Useful and undocumented in the spec: `query_first_timestamp` /
`query_last_timestamp` (return `pd.Timestamp`), `get_intervals` (returns
`list[tuple[int, int]]` of ns bounds), `get_missing_intervals_for_request`
(Step 4 idempotent re-ingest), `consolidate_data` (merges fragmented files), and
`funding_rates()` — which exists, and would be the hook if perpetuals are ever
added.

### D3 — `Currency.from_str` fabricates unknown currencies

**Observed:** 1.231.0 · **Affects:** `data/instruments.py` (Step 2), any code resolving a currency code

`Currency.from_str(code)` does **not** raise on an unrecognised code. It invents
one and returns it:

```python
>>> Currency.from_str("NOTACURRENCY")
Currency(code='NOTACURRENCY', precision=8, iso4217=0, name='NOTACURRENCY', currency_type=CRYPTO)
```

A typo in exchange metadata therefore yields a plausible-looking instrument
denominated in a currency that does not exist, priced to 8 decimal places, with
no error anywhere. This is exactly the class of silent wrongness §13 warns
about.

`strict=True` returns `None` for an unknown code — it still does not raise:

```python
>>> Currency.from_str("NOTACURRENCY", strict=True) is None
True
```

**Always pass `strict=True` and check for `None`.** `engine.data.instruments`
does this in `_currency` and raises `InstrumentError`. `Currency.from_internal_map`
behaves the same way but misses currencies added via `Currency.register`, so
`from_str(..., strict=True)` is preferred.

---

### D4 — Binance kline close time is one millisecond short of the close

**Observed:** Binance spot `/api/v3/klines`, 2026-09-07 · **Affects:** `data/ingest.py` (Step 4)

Not a Nautilus deviation — an exchange one — but it lands in exactly the place
spec §4.2 warns about, so it is recorded here.

A kline row carries two timestamps:

| Index | Field | 15m bar opening 2024-01-01T00:00:00Z |
|---|---|---|
| 0 | open time | `1704067200000` |
| 6 | "close time" | `1704068099999` |

Field 6 is **`open + interval - 1ms`**, not the close. The true bar close is
`1704068100000`. Using field 6 as `ts_event` puts every bar 1ms before its real
close; using field 0 puts it a whole interval early.

**Step 4 must compute `ts_event = open_time + interval`, from field 0.** Neither
returned timestamp is correct as-is. There is a test in Step 4 that fails if the
interval addition is removed (spec §13, pitfall 2).

Also worth knowing:

- **`minNotional` moved.** It now lives under filter type `NOTIONAL`, not the
  older `MIN_NOTIONAL`. The live value for BTCUSDT is `5.00000000`; the value in
  Nautilus's own `TestInstrumentProvider.btcusdt_binance()` is `10.00000000`, so
  the test fixture and the real venue disagree. Ingest uses the venue.
- **Public `exchangeInfo` carries no fee tiers.** `SpotInstrumentSpec` therefore
  sets `maker_fee` and `taker_fee` to `Decimal(0)`. Fees are a mandatory backtest
  request input (§7.3) and must never be inferred at ingest — a guessed fee would
  silently become the number every result is built on.

---

### D5 — `ParquetDataCatalog` refuses writes with overlapping intervals

**Observed:** 1.231.0 · **Affects:** `data/ingest.py` (Step 4), any incremental re-ingest

A catalog file is named for the `[min, max]` `ts_event` range it holds, and a
write whose range overlaps an existing file is rejected outright:

```
ValueError: Writing file 2023-12-25T00-15-00Z_2024-01-01T00-15-00Z.parquet with
interval (1703463300000000000, 1704068100000000000) would create non-disjoint
intervals. Existing intervals: [(1704068100000000000, 1704672000000000000)]
```

**Touching endpoints count as overlapping.** In the example above the new range
*ends* exactly where the existing range begins, and that is still refused.

Consequences for incremental ingest, both of which cost a real bug each:

1. **Only fetch the gaps.** Re-fetching a whole window to extend it by a day
   rewrites bars already held and is rejected. Ask
   `get_missing_intervals_for_request` what is missing and fetch only that.
2. **Snap both ends of a gap to the bar grid.** The catalog reports gaps in
   close space, bounded one nanosecond short of neighbouring data. Round the
   gap start **up** and the gap end **down** before converting to an open-time
   fetch window; otherwise a backward extend fetches the one bar that closes
   exactly where existing data starts, and hits the error above.

`consolidate_data(Bar, identifier)` merges fragmented files after the fact and
is the tool to reach for if a catalog ends up with many small ones.

**Also: coverage must be checked in close space.** Bars are keyed by close, so
a request for the window `[00:00, 01:00)` of 15m bars is asking about bars
closing at `00:15 .. 01:00`. Querying coverage with the raw window start always
reports the first interval as missing and re-fetches a fully ingested window.

---

### D6 — `Bar` validates OHLC relationships at construction

**Observed:** 1.231.0 · **Affects:** test fixtures anywhere bars are built by hand

`Bar(...)` enforces `low <= open <= high` and `low <= close <= high`, raising
`ValueError: low was > close` (or similar) rather than storing an impossible
bar.

Welcome, and worth knowing when writing fixtures: a helper that mutates `high`
or `low` in isolation produces bars the engine would reject anyway. Change OHLC
as one consistent set — see `rebuild()` in `tests/data/test_quality.py`.

This means the quality monitors do **not** need to check OHLC coherence; that
invariant is already unrepresentable.

---

### D7 — `RelativeStrengthIndex` reports 0..1, not 0..100

**Observed:** 1.231.0 · **Affects:** `dsl/indicators.py` (Step 7), every RSI condition

Nautilus's RSI is normalised to the unit interval:

```
RSI over 500 random-walk bars:  min=0.0625  max=0.9175
```

Every RSI reference in the world — and every spec anyone will write — uses
0..100. A condition reading `{"indicator": "rsi", "operator": "crossesAbove",
"value": 30}` against the raw value therefore **can never be true**, and the
backtest returns zero trades.

That failure is invisible: no error, no warning, and a result identical to a
strategy that legitimately found no signals. It was caught only by running the
strategy against real catalog data and finding 0 signals over 1,332 evaluated
bars where 95 were expected.

`ScaledSeries` in `dsl/indicators.py` multiplies by `RSI_SCALE = 100.0`. The
conversion belongs in the registry because that module is where DSL vocabulary
is mapped onto Nautilus, and nothing downstream should need to know.

`SimpleMovingAverage`, `ExponentialMovingAverage` and `AverageTrueRange` all
report in **price units** and need no scaling. Any indicator added later must
have its output range checked the same way — assume nothing.

### D8 — `StrategyConfig` is a msgspec `Struct`, not a Pydantic model

**Observed:** 1.231.0 · **Affects:** `strategies/dsl_strategy.py` (Step 10)

`StrategyConfig` subclasses `msgspec.Struct` via `NautilusConfig`. It has no
`model_fields`, no `model_validate`, and no Pydantic validators. `frozen=True`
is passed as a class keyword, which is what spec §6 shows:

```python
class DslStrategyConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    spec: dict[str, Any]
```

msgspec decodes `InstrumentId` and `BarType` from their string forms, so
`ImportableStrategyConfig(config={"instrument_id": "BTCUSDT.BINANCE", ...})`
works with plain JSON values — which is what lets a spec travel from the
TypeScript caller to the worker as data.

---

### D9 — Reading backtest results: three things the spec does not mention

**Observed:** 1.231.0 · **Affects:** `backtest/runner.py` (Step 15), Phase 2 acceptance

**Reports live on `engine.trader`, not on the engine.** Spec §7.4 says to call
`generate_order_fills_report()` on the engine; `BacktestEngine` has no such
method. The methods are `engine.trader.generate_order_fills_report()`,
`.generate_positions_report()`, `.generate_orders_report()`,
`.generate_account_report(venue)`.

**`BacktestRunConfig.dispose_on_completion` defaults to `True`.** The engine's
cache is cleared before `run()` returns, so every report comes back empty and
the run looks like it produced nothing. Set `dispose_on_completion=False`,
extract, then call `engine.dispose()` explicitly — which is what §7.4 asks for
anyway ("dispose after extraction"), and matters because Nautilus engines hold
a lot of memory.

This cost real time: 74 orders submitted and filled, with `generate_orders_report()`
returning 0 rows. The Nautilus event log showed `OrderFilled` throughout.

**Exactly one column is non-deterministic: `init_id`.** Across repeated runs of
an identical config, every other column of the fills report is byte-identical —
prices, quantities, slippage, commissions, `ts_init`, `ts_last`, and even
`position_id`, `venue_order_id` and `last_trade_id`. `init_id` is a UUID4 minted
per order-initialized event and carries no information about the strategy or
the result.

`BacktestVenueConfig(use_random_ids=False)` does **not** change this.

So "byte-identical fills" (§6) is asserted over the whole report **less
`init_id`**. Excluding more than that would weaken the guarantee; excluding
less makes it untestable.

---

### D10 — An exception in `on_start` does not fail the backtest

**Observed:** 1.231.0 · **Affects:** `backtest/runner.py` (Step 15)

If a strategy raises in `on_start` -- for example because its instrument is not
in the cache -- Nautilus logs the error, leaves the engine in an invalid state,
and the run **completes successfully**:

```
[ERROR] BACKTESTER-001.DslStrategy: ... StrategySetupError: instrument NOTREAL.BINANCE is not in the cache
[ERROR] BACKTESTER-001: InvalidStateTrigger('STARTING -> DISPOSE') state STARTING
RunOutcome(fills=0, positions=0, closed_positions=0, realized_pnl=0, total_commission=0)
```

`node.run()` does not raise, and the reports come back empty. A misconfigured
backtest therefore reports **SUCCEEDED with zero trades**, which is exactly what
a strategy that legitimately found no signals reports. Nothing downstream can
tell them apart.

Raising from `on_start` is still right — but it cannot be the only guard.
`runner.check_data_available` therefore verifies, **in the parent, before
spawning anything**, that the catalog holds the requested bar type and that its
coverage overlaps the requested window, raising `NO_DATA_FOR_WINDOW` otherwise.

A zero-trade result is a legitimate outcome, so it must not also be how a
misconfigured run reports itself.

### D11 — A `multiprocessing` child can die without reporting

**Observed:** while building Step 15 · **Affects:** `backtest/runner.py`

Not a Nautilus deviation, but it surfaces the same way. The runner passes
results back over a `multiprocessing.Queue`. A child killed by the OOM killer,
or dead inside a native extension, puts nothing on that queue — and a parent
blocking on a single `queue.get(timeout=ceiling)` waits out the **entire**
timeout for an answer that is never coming. With a 900-second ceiling that is a
fifteen-minute hang per crashed job.

`_await_message` polls at 0.25s instead, checking `process.is_alive()` between
attempts, and raises `BACKTEST_FAILED` with the child's exit code as soon as it
is gone. It re-checks the queue once after observing the exit, since the child
may have written just before terminating.

---

### D12 — Orders fill at the signal bar's close, not the next bar's open

**Observed:** 1.231.0 with bar data · **Affects:** `strategies/dsl_strategy.py`, every result

Spec §6 says "signals evaluate on closed bars; entries are submitted for the
next bar". Nautilus's simulated exchange does not do that with bar data. An
order submitted from `on_bar` fills at **that same bar's close**:

```
signal on bar closing 2024-01-01T04:00:00Z   (O=42302.19 H=42358.84 L=42243.99 C=42330.49)
first fill: ts=2024-01-01T04:00:00Z  BUY  px=42330.49      <- the signal bar's close
next bar:   O=42330.50                                     <- not this
```

**This is not lookahead.** The close is a value the strategy had already
observed when it decided; no future bar is read. It is *optimistic* in a
different way: in reality you cannot transact at the closing print.

**Measured impact on this market.** Across all 70,170 bars of BTCUSDT 15m:

| | `|open[t+1] - close[t]|` as % of price |
|---|---|
| identical | 49.1% of bars |
| median | 0.000010% |
| p99 | 0.005517% |
| max | 0.454726% |

One round trip costs 30 bps — `0.300000%`. The median discrepancy is roughly
**30,000 times smaller than the transaction costs already modelled**. Crypto
trades continuously with no auction and no overnight gap, so there is nothing
for the assumption to hide.

**Left as-is, deliberately, and now documented rather than assumed.** Changing
it would mean fighting the simulated exchange's bar handling to buy an effect
smaller than the rounding on a single fee. A market with real gaps — equities
with overnight moves — would need this revisited before any result is trusted,
and that decision belongs with whoever adds that market.

A test pins the behaviour, so it cannot change silently.

---

### D13 — `RelativeStrengthIndex` defaults to EXPONENTIAL smoothing, not Wilder

**Observed:** 1.231.0 · **Affects:** `dsl/indicators.py`, every RSI result

`RelativeStrengthIndex(period)` takes an optional `ma_type` which defaults to
`EXPONENTIAL`. Every published RSI strategy, every textbook, and TradingView's
`RSI` all mean **Wilder's** smoothing — `alpha = 1/n`, not `2/(n+1)`.

Verified against an independent implementation on a deterministic series:

```
default        [60.0377, 61.0961, 62.2497, 36.9587, 38.4025]   == EXPONENTIAL
WILDER         [56.4568, 57.1499, 57.8721, 42.4591, 43.2726]   == independent Wilder
```

On real BTCUSDT 15m data the two differ by **up to 34 RSI points**, which is
the difference between "oversold" and "overbought". A spec saying
`crossesAbove 30` was being evaluated against a curve nobody else computes.

`dsl/indicators.py` now passes `ma_type=MovingAverageType.WILDER`. With that,
an independent unseeded Wilder implementation matches the engine to
**0.000000000000 across 1,986 bars** — see `tests/dsl/test_rsi_reference.py`.

**Note the seeding.** Nautilus's Wilder starts its average gain and loss at
zero and smooths in; it does not seed them with the first observation. Seeding
produces a curve that differs early and converges later, so a reference
implementation must match this choice or the comparison is meaningless in the
first few hundred bars.

**Impact on results.** Re-running six months of BTCUSDT 15m with the same spec:

| | EXPONENTIAL (before) | Wilder (after) |
|---|---|---|
| trades | 107 | 73 |
| total return | −19.94% | −12.67% |
| Sharpe | −1.60 | −1.20 |

A third fewer trades. Both golden files were regenerated deliberately, which is
what a golden file is for.

---

### D14 — `generate_positions_report()` returns prices as floats

**Observed:** 1.231.0 · **Affects:** `backtest/results.py`

`avg_px_open` and `avg_px_close` come back as Python floats, so an average that
should be `44622.99` arrives as `44622.990000000005`. Passing that through
`Decimal(str(value))` preserves the error, and it lands in the stored trade
table — a `Decimal` money field carrying float noise, which rule 4 exists to
prevent.

Found by comparing the engine against an independent replay: every PnL matched
exactly while the prices differed in the twelfth decimal place.

`build_trades` now takes the instrument's `price_precision` and quantizes to
it. The venue trades on a tick; that tick is the precision a price should
carry. `runner._price_precision` reads it from the catalog instrument, which is
the same metadata ingest wrote from `exchangeInfo`.

The commission arithmetic still accumulates in a different order on each side,
which shows up as a total difference around `1e-8` on ~150 USDT. That is float
epsilon, not a modelling difference, and the differential tests bound it
explicitly rather than rounding it away.

---

### D15 — `DatabaseConfig` cannot select a Redis logical database

**Observed:** 1.231.0 · **Affects:** `live/node.py`, deployment

Spec §9.2 says to keep the Nautilus cache on "a separate Redis logical DB (or
instance) from arq", and §10.4 asks for that separation to be asserted in
config validation. The first half is not available:

```python
DatabaseConfig.__struct_fields__
# type, host, port, username, password, ssl,
# connection_timeout, response_timeout, number_of_retries, ...
```

There is no `db`, no `database`, no index. A `redis://host:6379/5` URL's
trailing `/5` never reaches Nautilus, so a cache "on DB 5" and a queue "on DB 0"
both land on database 0 of the same instance — and a `FLUSHDB` aimed at the
queue erases live position state, which is precisely the outcome §9.2 exists to
prevent.

**Separation must therefore be by instance.** `assert_cache_is_isolated`
compares host and port and refuses a shared one, and a test asserts that a
differing logical database is *not* accepted as separation — because it looks
like compliance and is not.

Deployment consequence: live trading needs a **second Redis**, not a second
database index on the existing one.

---

### D16 — `TradingNode` construction blocks forever on an unreachable cache Redis

**Found:** Step 24, building the live control plane's entry point.

Constructing a node whose `CacheConfig.database` points at a Redis that is not
listening does not raise, and does not time out:

```
$ timeout 100 uv run python -c "... TradingNode(config=cfg) ..."
config built
# and nothing further, for 346 seconds, until SIGKILL
```

Two properties, and the second is the dangerous one:

* **No connection timeout is applied.** `DatabaseConfig` exposes
  `connection_timeout`, but the default path through `TradingNode.__init__`
  never surfaces the failure — the call simply does not return.
* **`SIGTERM` does not end it.** `timeout 100` fired and the process kept
  running; only `SIGKILL` ended it. Nautilus installs signal handling of its
  own, and a process wedged before the loop starts never reaches the point
  where it would be honoured.

**Why it matters here.** `Supervisor._start` awaits `runner.start()`, and a
`start` that never returns stalls the reconciliation pass — for *every*
account, not just the one being started, since the loop is sequential. A single
unreachable Redis would take the whole control plane down in the least legible
way available: no error, no log line, no exit.

**What was done.** `engine.live.main.preflight` pings both Redis instances
before the supervisor is constructed and refuses to start with a message naming
which one is down. A deploy that fails is a better outcome than a deploy that
wedges.

**Residual risk, stated rather than fixed.** The preflight covers boot. If the
cache Redis dies *while* the control plane is running, the next node start will
still hang, and the loop with it. Bounding `runner.start()` with a timeout means
running a blocking constructor in a thread and leaking that thread when it never
returns — a worse trade than it looks, and one better decided against a real
deployment than in the abstract. The soak run is where this should be revisited.

---

### D17 — Four ways a sandbox node comes up wrong, none of which raise

**Found:** Step 25, writing `engine.simulation` and the first test that actually
builds a `TradingNode`. All four had survived every test in the repo, because
until then nothing ever built one.

#### 1. `environment` defaults to `LIVE`

`TradingNodeConfig.environment` is `Environment.LIVE` unless set. A node running
a sandbox execution client while declaring itself live is asking for
reconciliation and connection behaviour to disagree with what is happening. Set
`environment=Environment.SANDBOX` explicitly.

`Environment` is importable from `nautilus_trader.common`, and is not in any
`__all__` — `from nautilus_trader.common.config import Environment` type-checks
as an implicit re-export and mypy rejects it.

#### 2. A missing client factory is logged, not raised

`TradingNodeBuilder.build_data_clients` and `build_exec_clients` both do:

```python
if name not in self._exec_factories:
    self._log.error(f"No `LiveExecClientFactory` registered for {name}")
    continue
```

So a node with no registered factories **builds successfully**, starts,
heartbeats, and reports itself healthy — with no data client and no execution
client. It trades nothing, and looks exactly like a strategy that found no
signals. Silently inert survives a smoke test in a way a crash does not.

There is a test that reproduces this deliberately
(`test_without_its_factories_a_node_builds_and_trades_nothing`), because the
behaviour is the reason registration is imperative and called from exactly one
place.

#### 3. The pure fix does not work — `ImportableConfig` hands over an instance

`ImportableConfig` carries a `factory: ImportableFactoryConfig`, and the builder
resolves it, which would make the wiring data rather than a call. It does not
work for sandbox:

```python
self._exec_factories[name] = cfg.factory.create()   # an INSTANCE
...
if factory.__name__ == "SandboxLiveExecClientFactory":   # only a CLASS has this
    factory_kws["portfolio"] = self._portfolio
```

```
AttributeError: 'SandboxLiveExecClientFactory' object has no attribute '__name__'
```

`add_exec_client_factory(name, factory)` stores the **class**, which is what the
`__name__` check needs and what `factory.create(...)` works on, since `create`
is a static method. So registration must be imperative, and a test asserts the
registered factories are classes.

The `__name__` comparison also means the sandbox client only receives the
`portfolio` kwarg it requires while that class keeps that exact name — asserted
rather than hoped for.

#### 4. `venue` is typed `Venue` but accepts a `str`

`BinanceDataClientConfig.venue` is annotated `Venue`. These configs are msgspec
`Struct`s, which do not validate or coerce on direct construction, so a string
is accepted and stored — and fails much later, inside a Cython constructor at
node-build time:

```
TypeError: Argument 'venue' has incorrect type
(expected nautilus_trader.model.identifiers.Venue, got str)
```

`SandboxExecutionClientConfig.venue` is annotated `str` and genuinely wants one.
Two adjacent fields with the same name, opposite types, and no validation on
either. Construct `Venue(...)` for the data client; pass the plain string to the
execution client.

**The general lesson, worth more than the four fixes.** Every one of these is a
failure that produces a *running, healthy-looking node*. Configuration tests
cannot find them, because the configuration is valid — the object graph is only
assembled at `build()`. A boot test that constructs and builds a real node is
not a nicety here; it is the only place this class of defect is visible.

---

### D18 — `TradingNode.dispose()` closes the event loop it was given

**Found:** Step 25, from a pytest teardown warning in the boot test. The most
serious of the findings, and the one nothing else would have surfaced.

```python
loop = self.kernel.loop
if not loop.is_closed():
    if loop.is_running():
        loop.stop()
        loop.close()
```

The docstring says "gracefully shuts down the executor and event loop", which is
correct and is the problem: Nautilus assumes **one node per process**, so the
node's loop is the process's loop and closing it is the last thing that happens.

`LiveNodeRunner` does not hold that assumption. It runs several accounts in one
process, all on one loop, alongside the supervisor. `stop()` called
`node.dispose()` — so stopping *one* account would have stopped the loop and
closed it, taking the supervisor and every other account down with it. In a
control plane whose entire purpose is surviving the failure of one account, the
stop path was a single point of failure.

**What was done.** `stop()` calls `node.stop()` and drops the reference. There
is a test asserting the loop is still open and usable afterwards.

**The cost, stated.** A stopped-but-undisposed node holds its cache and engines
until garbage collection, so an account cycled many times in one process leaks.
Accepted for now and not hidden.

**The real fix is the one the spec already asks for.** Section 10.1: "an account
is the unit of risk, credentials and reconciliation, so it is the unit of
process isolation". The code comments say that; the implementation runs every
account in one process. One OS process per account makes `dispose()` safe again,
because the loop really would be that account's own — and it makes a crashing
node crash alone. That is a step, and it should be taken before more than one
account runs on a box.

**How it was found is the point.** No configuration test can see this: the
config is valid, the call is correct in isolation, and the failure needs a
second account to be visible. It surfaced as a pytest warning about a closed
loop during teardown — which is the same failure, scaled down.

---

### D19 — Two ways a live node exits looking healthy

**Found:** Step 26, by starting a real child process and watching it die.

#### 1. Nautilus installs its own `SIGTERM` handler, replacing yours

`engine.live.worker` sets a handler that flips a stop event, then builds and
runs the node. Running the node replaces that handler:

```
[WARN] TradingNode: Received SIGTERM, shutting down
[INFO] TradingNode: STOPPED
```

The node stopped correctly — and the process **kept running**, because the stop
event the child was waiting on was never set. The parent's grace period elapsed
and SIGKILLed it: twenty seconds per stop, and the exit code of a process that
was killed rather than one that finished.

The fix is to stop treating the signal as the exit condition. The child waits on
`node.run_async()` **and** its own stop event, whichever completes first, which
makes Nautilus's handler the thing that ends the process — which it already was.

Measured after the fix: a healthy simulation node stops in **10.3 s**, spent
inside Nautilus awaiting engine disconnections (`timeout_disconnection`, 10 s by
default). **A stop grace shorter than that turns every ordinary stop into a
SIGKILL**, so `LiveNodeRunner`'s default is 20 s, and the relationship is stated
where the value is set.

#### 2. A live node's cache starts empty, and the strategy's complaint exits 0

A backtest is handed its instruments from the catalog. A live or sandbox node
fetches them from the venue, and only if an instrument provider is configured to
— the default is `load_all=False, load_ids=None`, which loads nothing.

So `DslStrategy.on_start` raised "instrument BTCUSDT.BINANCE is not in the
cache; was it written to the catalog?" — correct, and thrown at the worst
possible moment. It halted the node's start, the process exited with status
**0**, and from the parent it was indistinguishable from a clean shutdown.

```python
InstrumentProviderConfig(load_ids=frozenset([state.instrument_id]))
```

on both the data client and the sandbox execution client — the simulated
matching engine needs the instrument as much as the strategy does. `load_ids`
rather than `load_all`: Binance lists thousands, and fetching all of them to
trade one pair costs startup time and memory for nothing.

**With both fixed, a `DslStrategy` reached `RUNNING` against the live Binance
feed for the first time.**

**What both have in common** is the recurring theme of D17 and D18: the failure
mode of a live node is not an exception, it is a process that looks fine. One
exited cleanly having done nothing; the other stayed alive having stopped. The
only test that finds either is one that starts a real child and then asks
whether it is still there.

---

### D20 — A Binance instrument reports zero fees

**Found:** Step 28, in the first minute of the soak, from a single log line:

```
DslStrategy: cost rate 0 (from config)
```

An instrument loaded through `BinanceSpotInstrumentProvider` from the public
`exchangeInfo` endpoint carries:

```
maker_fee: 0    taker_fee: 0
```

Not a bug — public instrument data cannot know an account's fee tier. Real rates
are account-specific and live behind an authenticated endpoint
(`/sapi/v1/asset/tradeFee`), which needs a key, which ADR-001 forbids.

**Two consequences, and the second is the quiet one.**

The sandbox execution client hardcodes `fee_model=MakerTakerFeeModel()`, which
computes from those instrument fields — so **simulated fills are charged
nothing**, and a simulation's returns are optimistic by roughly a round trip's
commission.

And the fallback built in Step 27, resolving the cost rate from the instrument
when the config states none, resolves to zero here. The mechanism was right; the
assumption that the venue would tell us was wrong. So sizing left no room for a
commission — which is only harmless because the venue charged none either. The
day a key is loaded, the venue starts charging and the instrument still reports
zero.

**The fix is that it has to be declared.** `VenueFees` is now a required field
on a live account: maker, taker and slippage, exactly as a backtest request
carries them (rule 5), with `cost_bps = taker + slippage` — the same sum
`backtest/builder.py` uses, so a strategy is sized identically in both. A
declared zero is still allowed, because a venue that charges nothing is a real
answer; a *defaulted* zero is not.

The instrument fallback is kept, below the declaration. It is right for any
venue that does report fees, and it is what a future authenticated provider
would populate.

**And adding one required field to a stored model made every existing record
unreadable**, which surfaced something worse than the fees: `reconcile_once`
raised out of the loop, so one bad record stalled the pass for **every** account.
A local failure with a global blast radius, the same shape as the crash loop.
Each account is now isolated, and an unreadable record leaves its node running
— the node holds the position; the record only describes it.

---

### D21 — Binance's order vocabulary is not Nautilus's

**Found:** Step 30, by comparing the cache reader and the venue reader against
*each other* rather than each against its own fixture.

Binance reports an order resting on the book as `NEW`. Nautilus calls that state
`ACCEPTED`. Startup reconciliation compares the two views field by field, and
status is one of the fields:

```
ORDER_STATUS_DIFFERS on O-1: cache=ACCEPTED venue=NEW
```

**Every open order at startup would have read as a discrepancy, and the account
would have halted** — a node refusing to start on its first live run, over a
spelling difference, with an error that looks like a genuine disagreement about
money.

`BINANCE_ORDER_STATUS` now translates, and an **unmapped** status is returned
unchanged rather than guessed at: a status this code has never seen is exactly
the case where starting anyway is wrong, so it surfaces as a discrepancy and
halts.

There is also a test asserting every mapped *value* is a real
`OrderStatus` name — a typo there would map onto a word Nautilus never produces,
and the account would halt every start with no clue why.

**Why it was only findable this way.** Each reader tested against its own
fixture passes: the fixtures would have been written by the same hand, in the
same vocabulary, on the same afternoon. It takes comparing the two halves that
must agree in production to see that they do not.

