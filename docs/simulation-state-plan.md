# Simulation state — plan for review

**Status:** approved 2026-09-24. Phase 1 (engine) built on `feat/simulation-state`, awaiting review. Depends on PR #9 (simulations can trade, charge fees
and keep their balance), which fixed the five defects this plan's research found.

## The answer first

A simulation page today shows **control-plane metadata only**: what was asked for, what the
node reports, the heartbeat, the kill switch and the account configuration. It cannot answer the
questions a user actually has about a running paper account:

- How much is it worth now, and is it up or down?
- Is it holding a position? At what entry, and what is it worth?
- What has it traded, and when?
- What is the strategy doing right now — still warming up, waiting for an entry, or waiting for
  an exit? What are its indicators reading?
- Did it try to trade and get blocked? Why?

None of that is missing because the frontend skipped it. **The engine does not expose it.** The
trading state lives inside the node's own OS process, and the only thing that process sends out is
a heartbeat. This plan adds one channel out of that process, then carries it through Hono to the
page.

Roughly 50% of the work is in `packages/engine_server`, 20% in `apps/server` and
`packages/contracts`, and 30% in `apps/web`.

---

# 1. What exists today

Verified by reading the code and the running Redis instances, not assumed.

## Where each piece of state lives

| State | Where | Readable by the API today? |
|---|---|---|
| Desired state (spec, revision, risk, fees) | Redis `live:desired:{accountId}` | Yes — `GET /v1/live/{id}` |
| Observed state (status, revision, heartbeat, error) | Redis `live:observed:{accountId}` | Yes — same call |
| Lease holder | Redis `live:lease:{accountId}` | Yes — same call |
| Kill switch | Redis + a file | Yes — `GET /v1/live/{id}/kill` |
| **Balances, positions, orders, fills** | Nautilus cache, in the node process, persisted to the **separate** `redis-cache` instance | **No** |
| **Indicator values, signals, blocked entries** | `DslStrategy` in memory, plus log lines | **No** |
| **Equity over time** | Nowhere | **No** |

## The process boundary

```text
Hono ──> FastAPI (engine api)  ──reads──>  redis        live:desired / observed / lease
                                                          ▲
engine live (supervisor) ──spawns──> child process        │ heartbeat every 15s
                                      ├─ TradingNode ─────┘
                                      ├─ DslStrategy        ← signals, indicator values
                                      ├─ SandboxExecClient  ← simulated fills, balances
                                      └─ Nautilus Cache ──> redis-cache   (msgpack, Nautilus-internal)
```

`engine/live/node.py` is explicit about it: *"The parent holds no Nautilus object at all. What
crosses is JSON."* The only JSON that crosses today is the heartbeat (`engine/live/worker.py`,
`tend()`).

## What the Nautilus cache actually holds

Scanned from `redis-cache` on the running stack, per account:

```text
trader-NT-SIM5224E419C8A0E4D23:accounts:BINANCE-001
trader-NT-SIM5224E419C8A0E4D23:currencies:SOL
trader-NT-SIM5224E419C8A0E4D23:currencies:USDT
trader-NT-SIM5224E419C8A0E4D23:instruments:SOLUSDT.BINANCE
```

No orders or positions yet, since none of the three accounts has traded. Once they do, Nautilus
adds `orders:*` and `positions:*` keys. **Reading these directly from the API is ruled out:** they
are msgpack-encoded Nautilus objects in a layout Nautilus owns and may change between versions,
and decoding them would pull `nautilus_trader` into the API process for no benefit.

---

# 2. Decisions this plan makes

### S1 — The node publishes a snapshot; nobody reads Nautilus's cache from outside

The child process already has the live `Cache` and `Portfolio`. It writes a small JSON snapshot
of them to the **control-plane** Redis on the same loop that heartbeats. The API reads that key.
This keeps the existing rule intact — only JSON crosses the process boundary — and keeps the
Nautilus cache a private detail of the node.

### S2 — Three shapes of data, three Redis structures

| Data | Shape | Redis structure | Bound |
|---|---|---|---|
| **Snapshot** — balances, position, open orders, P&L, strategy state | Latest value only | `SET live:snapshot:{id}` (JSON) | 1 key |
| **Activity** — fills, signals fired, entries skipped or blocked, starts and stops | Append-only event log | `XADD live:events:{id}` with `MAXLEN ~ 1000` | ~1,000 events |
| **Equity curve** — one point per closed bar | Append-only series | `XADD live:equity:{id}` with `MAXLEN ~ 5000` | ~52 days of 15m bars |

Redis streams rather than lists, because an entry id is a timestamp: "everything after the last
id I saw" is `XRANGE id +`, which is what incremental polling wants.

### S3 — Snapshot every 5 seconds, events as they happen

The heartbeat is every 15 seconds, which is too slow for a price to feel live. The snapshot
moves to its own 5-second cadence inside `tend()`. Events are written when they occur, from the
strategy's own handlers (`on_order_filled`, `_decide`, `_enter`), not polled.

### S4 — Money stays a string

As with backtests (frontend plan D7): every price, quantity, balance and P&L crosses as a decimal
string, formatted only at the pixel.

### S5 — Postgres keeps fills (phase 4, optional)

Redis is a cache (frontend plan D1). A `FLUSHDB` or a lost volume erases the activity log. Fills
and closed trades are the part a user would miss, so Hono copies them into Postgres the way it
copies a backtest's terminal outcome — on read, idempotently, keyed by the fill's trade id. The
snapshot and equity curve stay Redis-only; they can be rebuilt going forward.

### S6 — A restart is shown, not hidden

Balances carry across a restart (D26). The snapshot still carries `sessionStartedAt`, and the
activity feed logs `NODE_STARTED` with the revision, so a gap in the equity curve has a visible
reason.

---

# 3. Defects found while writing this — fixed in PR #9

Running a simulation that trades, to test the restart behaviour, found that **no simulation could
trade at all**. Each fix uncovered the next. Details are in
`packages/engine_server/docs/nautilus-api-notes.md`.

| # | Defect | Effect before the fix |
|---|---|---|
| D22 | Risk gate refreshed on a monotonic clock, checked on Unix time | Every entry blocked |
| D23 | Sandbox exchange never subscribed to bars | Every order rejected, "no market" |
| D24 | Account loaded from the cache before it was marked as calculated | From the second start on, fills moved the position but not the balance |
| D25 | Sandbox charged the instrument's fee, which Binance reports as zero | No fees charged |
| D26 | Sandbox reset the account on every start | A restart put balances back to 10,000 USDT, keeping the position |

**What this means for the plan:**
- **Balances survive a restart**, so a restart no longer splits the history. `sessionStartedAt`
  stays in the snapshot for display, but S6's "balances reset" notice is no longer needed.
- **Fees are the backtest's.** A simulated fill costs `notional × (taker + slippage) bps`, the
  same as a backtest, so the two are comparable.
- **Checked on the running stack:** buy at 10,000 → 9,799.76 USDT + 1.74 SOL → restart →
  unchanged → sell → 9,999.49 USDT.

---

# 4. What we can build

Grouped by what the user sees. Each item names its data source.

## 4.1 Performance header

| Field | Source |
|---|---|
| Equity (cash + coin × last price) | snapshot |
| Return vs starting balance, % and absolute | snapshot |
| P&L | snapshot — equity − baseline. Not `Portfolio.realized_pnl`, which loses a reopened position's history on restart (D27) |
| Unrealised P&L (open position) | snapshot — (last close − average entry) × quantity |
| Realised P&L | snapshot — P&L − unrealised |
| Max drawdown this session | computed from the equity stream |
| Trades closed, win rate | snapshot counters, or computed from events |

## 4.2 Position

- Open position: side, quantity, average entry, last price, market value, unrealised P&L and %,
  time held.
- The stop-loss level implied by the spec (`_stop_loss_percent`), so the user sees where an exit
  would fire.
- Otherwise: **Flat**, with the time since the last exit.

## 4.3 Balances and open orders

- Every non-dust balance (USDT, SOL): total, free, locked.
- Open orders: side, quantity, type, status, submitted at. Normally empty; a market order fills on
  the next bar.

## 4.4 Strategy — what it is doing right now

| Field | Source |
|---|---|
| Phase: **Warming up** (n / N bars), **Waiting for entry**, **In position, waiting for exit**, **Blocked** | snapshot — `bars_seen`, `warmup_bars`, position state, gate |
| Last bar: time and close | snapshot |
| Next bar expected at | computed from the bar type |
| Current indicator values (e.g. RSI 14 = 41.2) | snapshot — the `values` dict `_decide` already builds |
| The entry or exit rule being checked, with each condition marked true or false | snapshot + the spec tree |
| Counters: bars seen, orders submitted, orders blocked | `DslStrategy` fields that already exist |

The condition breakdown is the most useful item for someone who wrote the rules: *"entry needs
RSI < 30 **and** close > SMA 200 — RSI is 41.2 (not yet), close is above the SMA (yes)."*
Evaluating each leaf separately means a small change to `engine/dsl`, returning per-node results
instead of one boolean.

## 4.5 Activity feed

A reverse-chronological log, filterable by type:

| Event | Written from | Carries |
|---|---|---|
| `NODE_STARTED` / `NODE_STOPPED` | `run_account` | revision, reason |
| `SIGNAL` | `_decide`, when triggered | side, indicator values |
| `ENTRY_SUBMITTED` / `EXIT_SUBMITTED` | `_enter` / `_exit` | quantity, notional |
| `ENTRY_SKIPPED` | `_enter` | sizing outcome (e.g. below minimum notional) |
| `ENTRY_BLOCKED` | `_enter` | gate breach and reason, mandate id |
| `FILL` | `on_order_filled` | side, quantity, price, fee, trade id |
| `POSITION_CLOSED` | `on_position_closed` | entry, exit, realised P&L, duration |
| `KILL_ENGAGED` / `KILL_RELEASED` | `tend`, on change | — |

All of these already exist as log lines except `FILL` and `POSITION_CLOSED`. The change is to also
write them to the stream.

## 4.6 Equity chart

`components/backtests/equity-chart.tsx`, the one the backtest result page uses, fed from `live:equity:{id}`. One point
per closed bar, with markers for fills and a break at each restart (S6).

## 4.7 Trades table

Closed round trips — entry time and price, exit time and price, quantity, P&L, fees, duration.
This is the same shape as the backtest trades table, so `components/backtests/trade-table.tsx` is
reused. Built from `POSITION_CLOSED` events, or from Postgres after phase 4.

## 4.8 List and dashboard

Add **Equity**, **Return** and **Position** columns to the simulations table and the dashboard
card, read from the snapshot each row already fetches.

## 4.9 Out, deliberately

- **Push (SSE or WebSocket).** Polling every 5 seconds is enough for 15-minute bars (frontend plan
  D4). Revisit if the timeframe drops below a minute.
- **Manual orders and a Flatten button.** Letting a user trade a paper account by hand muddies
  what the strategy did. Flatten is a real need, but it belongs with the stop semantics decision
  in section 3.
- **Tick-level prices.** The strategy trades bars. The last price is the last bar close, or the
  last trade if the data client already subscribes to it.
- **Comparing against the backtest.** "Live is tracking 2% behind the backtest over the same
  window" is valuable, but it needs a backtest re-run over the live window. It gets its own plan.

---

# 5. Engine — the work

## 5.1 A publisher in the child — `engine/live/publisher.py` (new)

```python
class StatePublisher:
    """Writes the node's state to control-plane Redis. JSON only (node.py's rule)."""

    def __init__(self, redis, account_id: str, node) -> None: ...
    async def snapshot(self) -> None:             # SET live:snapshot:{id}
    async def event(self, kind: str, **fields):   # XADD live:events:{id} MAXLEN ~ 1000
    async def equity_point(self, ts, equity):     # XADD live:equity:{id} MAXLEN ~ 5000
```

`snapshot()` reads `node.cache` and `node.portfolio`: account balances, `positions_open`,
`orders_open`, realised and unrealised P&L, and the strategy's `status()` (5.2).

**Strategy handlers are synchronous and run on the node's loop.** They must not await Redis.
They append to an in-memory `collections.deque`, and `tend()` drains it on each tick. A slow
Redis then delays the activity feed, not the strategy.

## 5.2 `DslStrategy` additions

- `status() -> dict` — phase, `bars_seen`, `warmup_bars`, last bar time and close, the latest
  `values`, per-condition results, counters.
- `on_order_filled` and `on_position_closed` handlers that push `FILL` and `POSITION_CLOSED`.
- `_decide`, `_enter` and `_exit` push the events listed in 4.5 alongside the log lines they
  already write.
- An `events` deque, set on the built instance by `attach_gate` in the same way `risk_gate` is.
  Backtests leave it `None` and pay nothing.

**It must not change what a backtest computes.** The existing backtest golden tests are the gate.

## 5.3 `tend()` gets a third cadence

`tend()` today does kill-switch refresh + heartbeat. It adds: drain the event deque (every tick),
write the snapshot (every 5s), write an equity point (on each new bar).

## 5.4 API endpoints — `engine/api/routes/live.py`

| Call | Returns |
|---|---|
| `GET /v1/live/{id}/snapshot` | the snapshot, or `404 SNAPSHOT_NOT_FOUND` before the first write |
| `GET /v1/live/{id}/events?after={streamId}&limit=` | `{events: [...], last: streamId}` |
| `GET /v1/live/{id}/equity?after={streamId}` | `{points: [{time, equity}], last}` |

A snapshot older than the heartbeat timeout is returned with `stale: true` rather than hidden;
the last known state of a dead node is still the most useful thing to show.

## 5.5 Snapshot shape

```json
{
  "at": "2026-09-24T10:15:05Z",
  "sessionStartedAt": "2026-09-24T02:34:11Z",
  "revision": 3,
  "startingBalance": { "currency": "USDT", "amount": "10000" },
  "equity": "10184.22",
  "realizedPnl": "142.10",
  "unrealizedPnl": "42.12",
  "balances": [
    { "currency": "USDT", "total": "4031.80", "free": "4031.80", "locked": "0" },
    { "currency": "SOL",  "total": "41.2",    "free": "41.2",    "locked": "0" }
  ],
  "position": {
    "side": "LONG", "quantity": "41.2", "avgEntry": "148.31",
    "lastPrice": "149.33", "openedAt": "2026-09-24T08:45:00Z", "stopPrice": "143.86"
  },
  "openOrders": [],
  "strategy": {
    "phase": "IN_POSITION",
    "barsSeen": 612, "warmupBars": 200,
    "lastBar": { "time": "2026-09-24T10:15:00Z", "close": "149.33" },
    "values": { "rsi_14": "58.41", "sma_200": "146.02" },
    "checking": "exit",
    "conditions": [{ "path": "exit.0", "label": "RSI 14 > 70", "value": false }],
    "ordersSubmitted": 3, "ordersBlocked": 0
  }
}
```

## 5.6 Tests

- The publisher against a fake cache and portfolio: the snapshot shape, `MAXLEN` trimming, and
  draining the deque.
- A sandbox node test (the existing one in `tests/`) that asserts a snapshot key appears.
- Backtest golden tests unchanged.

---

# 6. `apps/server` and `packages/contracts` — the work

- `packages/contracts/src/simulation.ts`: `SimulationSnapshot`, `SimulationEvent` (a
  discriminated union on `kind`), `EquityPoint` (reuse the backtest one).
- Three routes, each behind the ownership check `SimulationService.own()` already does:

  | Route | Engine call |
  |---|---|
  | `GET /api/v1/simulations/{id}/snapshot` | `/v1/live/{accountId}/snapshot` |
  | `GET /api/v1/simulations/{id}/events?after=&limit=` | `/v1/live/{accountId}/events` |
  | `GET /api/v1/simulations/{id}/equity?after=` | `/v1/live/{accountId}/equity` |

- `list()` adds `equity`, `returnPct` and `position` to each row. That is one extra keyed read
  per row. It still never calls the engine's list endpoint.
- The engine's stream ids are opaque cursors. The client passes back the `last` value it was
  given, and never a raw engine path (frontend plan D2).

---

# 7. `apps/web` — the work

- `lib/api/simulations/`: query options for snapshot, events and equity.
  - Snapshot polls every 5s while the account is live, using `pollOnceLoaded`.
  - Events and equity fetch incrementally with `after=` and append to the cached array.
- `app/(protected)/simulations/[id]/page.tsx` gets tabs:
  - **Overview:** the performance header, position and strategy panels, and the equity chart.
  - **Activity:** the event feed.
  - **Trades:** the closed round trips.
  - **Settings:** today's state and configuration cards, unchanged.
- New components under `components/simulations/`:
  - `performance-cards.tsx`
  - `position-card.tsx`
  - `strategy-status.tsx`
  - `activity-feed.tsx`
- `simulation-table.tsx`: new Equity, Return and Position columns.
- Empty and edge states:
  - **No snapshot yet:** "Starting — the first update arrives within a few seconds."
  - **Warming up:** a progress bar showing n of N bars and the time left.
  - **Stale:** "Last update 4 min ago — the node is not reporting."
  - **Restarted:** the session note described in S6.

---

# 8. Built so live can reuse it

Real-money trading is `mode: LIVE` on the same account record. Checked against the code, it
shares almost everything this plan touches:

- **One strategy class.** `DslStrategy` runs unchanged in backtest, simulation and live (ADR-001,
  "one execution path"). Signals, blocked entries and `on_order_filled` fire the same way.
- **One node.** `build_node_config` differs by mode in exactly one place: the execution client
  (`SandboxExecClient` today, the Binance one for live). The `Cache` and `Portfolio` the
  publisher reads are identical.
- **One control plane.** `/v1/live/{accountId}` already carries `mode`. The supervisor, the kill
  switch, the heartbeat and the new endpoints are keyed by account, not by mode.

So the publisher, the endpoints, the Redis layout and the web panels work for live with no
change, **provided the rules below are followed now.** Each one costs almost nothing in phases
1–3. Retrofitting any of them later means a contract change across three packages.

## The rules

| # | Rule | Why live needs it |
|---|---|---|
| L1 | **No mode checks in the state code.** The publisher, endpoints, contracts and components never branch on `SIMULATION`. Mode is one field in the snapshot, shown as a badge. | Otherwise every file gets a second branch later. |
| L2 | **The baseline is recorded, not assumed.** The snapshot carries `baseline {currency, amount, at}`, captured from the account on its first start. Never read from `STARTING_BALANCES`. | Live starts with whatever is in the exchange account, not 10,000 USDT. |
| L3 | **Net external flows out of the baseline.** P&L is equity − baseline (D27 rules out Nautilus's realised P&L), so live must add deposits and subtract withdrawals from the baseline. Return is `P&L / baseline`. | A deposit or withdrawal changes live equity without any trade. |
| L4 | **Scope to the strategy's instrument.** Equity counts the instrument's base and quote currencies. Other balances are listed separately as "Other holdings". | A real account holds coins the strategy never touched. |
| L5 | **Fees carry their currency.** `commission: {amount, currency}` on every fill, never assumed USDT. | Binance can charge fees in BNB. |
| L6 | **One event per fill, keyed by trade id.** An order can have several fills. | Partial fills are rare in simulation and normal in live. |
| L7 | **An open event vocabulary.** `kind` is a string, and the feed renders unknown kinds generically. | Live adds `RECONCILED`, `RECONCILIATION_FAILED`, `MANDATE_REVOKED` and venue rejects. |
| L8 | **No secrets in the snapshot.** Built from an allowlist of fields, never by dumping the desired state. It never contains `credential_ref`. | A live snapshot sits next to a real account. |
| L9 | **Mode-neutral names below the route.** The service is `AccountStateService`, components go in `components/accounts/`, and the Prisma table is `AccountFill` with an `accountId` column. The `/simulations` URLs can stay. | Live reuses the service, components and table under its own routes. |

## What changes for live, and what doesn't

| Area | Simulation | Live | Work when live arrives |
|---|---|---|---|
| Publisher, endpoints, Redis layout | this plan | same | none |
| Strategy events | this plan | same, plus the L7 kinds | emit 3 extra kinds from `recovery.py` and the mandate poll |
| Baseline | first start | first start | none, given L2 |
| Restart | resets to 10,000 today (section 3) | the exchange is the truth, so nothing resets | none. Option 1 of section 3 makes simulation behave like live. |
| Durable fills (phase 4) | optional | **required** — real money needs an audit trail | the phase 4 table, already generic under L9 |
| Hono | `SimulationService.put()` hard-codes `mode: 'SIMULATION'` | needs `mode` and a credential reference | a `mode` column on the account row, plus the credential flow |
| Web | panels | same panels, plus a LIVE badge and a confirm step on Start | small |

## What makes live hard is not this feature

The expensive part of live is ADR-001's ship conditions: a secrets manager, reconciliation
proven against real Binance (`readers.py` says it has never run), mandates, and a stated paper
period. None of that is touched here.

This work does help with one of them. **Condition 7 asks for paper fills to be compared against
a backtest over the same window.** The fill stream and the phase 4 table are exactly the input
that comparison needs.

## Verdict

**Easy, if L1–L9 are part of phases 1–3.** Moving this feature to live is then about a day:

- a mode badge;
- three extra event kinds;
- phase 4 changes from optional to required.

Without the rules, the baseline, fee and naming assumptions would each need a contract change
later.

---

# 9. Build sequence

| Phase | Scope | Gate |
|---|---|---|
| **0 — Decide** | ✅ Done 2026-09-24 — see Decisions below | — |
| **1 — Engine** | Publisher, strategy status and events, `tend()` cadence, three endpoints, tests | `curl /v1/live/{id}/snapshot` on the running stack returns the shape in 5.5; backtest golden tests pass |
| **2 — Server** | Contracts, three routes, list columns | Route tests; another user's id returns 404 |
| **3 — Web** | Tabs, the new panels, activity feed, equity chart, list columns | Manual pass on a running simulation; axe clean |
| **4 — Durable fills** *(approved for v1; required for live)* | `AccountFill` table in Prisma, copied on read | A `FLUSHDB` on `redis` leaves the trades tab intact |

Each phase gets its own branch and your review, as in the frontend v1 plan.

## Decisions (2026-09-24)

| Question | Decision |
|---|---|
| Restart behaviour (section 3) | **Carry balances forward.** Built in PR #9 (D26). |
| Live readiness (section 8) | **Yes.** Rules L1–L9 are part of phases 1–3. |
| Per-condition breakdown (4.4) | **Phase 1.** Includes the `engine/dsl` change to evaluate each leaf. |
| Durable fills | **Phase 4, in v1**, straight after the page works. |

---
---

# Summary : 

Plan

1. Engine: the running node reports what it's doing
- Account snapshot, written every few seconds:
  - Cash and coin balances.
  - Equity, and return against the 10,000 USDT start.
  - Realised P&L, plus unrealised P&L on the open position.
  - The open position: quantity, entry price, last price.
  - Open orders.
- Strategy state:
  - Warming up (X of N bars) or live.
  - Last bar time and close.
  - Current indicator values.
  - Whether entry or exit rules are being checked.
  - Counts of orders submitted and blocked.
- Recent activity (last 500):
  - Fills.
  - Signals that fired.
  - Entries skipped or blocked by the risk gate, with the reason.
- Equity history: one point per bar, for a chart.
- Storage: all of this goes in Redis next to the heartbeat, so the page can read it without touching the node.
- New engine endpoints: GET /v1/live/{id}/snapshot and GET /v1/live/{id}/activity.

2. Server and contracts
- Hono routes for these, with the same ownership check as the existing simulation routes.
- Zod schemas for the new data.

3. Web: new sections on the simulation page
- Performance cards: equity, return %, realised and unrealised P&L.
- Position: the open position, or "Flat".
- Equity curve chart.
- Strategy: warm-up progress, latest indicator values, last bar.
- Activity feed: fills, signals and blocked entries.
- Polling: every 5–10s while the simulation is running.

Open questions

1. Keeping history. Redis is fine for the current state, but fills would be lost on a Redis flush. I suggest also copying fills into Postgres, the same way backtest results are kept. That could be a follow-up step.
2. Restarts. I need to check whether the simulated account resets to 10,000 USDT when the node restarts, for example after a new revision or a deploy. If it does, P&L and the equity history would restart as well, and the page should say so.