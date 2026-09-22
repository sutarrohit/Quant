# Every field of a backtest and a live request

The complete input contract for the two endpoints that take a strategy, with
every option, every bound, and what happens when you leave something out.

| | Backtest | Live |
|---|---|---|
| Call | `POST /v1/backtests` | `PUT /v1/live/{account_id}` |
| Model | `backtest/request.py` | `api/routes/live.py:61` |
| Keyed by | `requestId` in the body | `account_id` in the URL |
| Runs | once, over a window | until stopped |
| Auth | `Authorization: Bearer <NT_INTERNAL_API_KEY>` | same |
| Unknown field | `422` | `422` |

Both carry the **same `spec`**, byte for byte. Part 1 covers it once; parts 2
and 3 cover the wrapper around it.

---

# Part 1 — the `spec`

`src/engine/dsl/schema.py`. Every model is frozen and `extra="forbid"`: a
typo'd field is a hard error, because `stopLosPercent` silently ignored is a
strategy running without a stop.

All keys here are **camelCase**. Every number is parsed as `Decimal` — send
`"4"` or `4`, never `4.0000000001`-style floats you care about, since a spec is
hashed into an identity and a float that doesn't round-trip changes that hash.

## Everything at once

Valid, and validated against the real models — every construct the DSL has:

```jsonc
{
  "strategyId": "kitchen-sink",   // REQUIRED. 1-128 chars, ^[a-zA-Z0-9][a-zA-Z0-9._-]*$
  "version": 1,                   // REQUIRED. integer >= 1

  "market": {                     // REQUIRED
    "exchange": "binance",        // REQUIRED. only "binance" exists today
    "marketType": "spot",         // REQUIRED. only "spot" exists today
    "symbols": ["SOL/USDT"],      // REQUIRED. 1-8 entries, human spelling with the slash
    "timeframe": "15m"            // REQUIRED. 1m | 5m | 15m | 1h | 4h | 1d
  },

  "entry": {                      // REQUIRED. a condition tree
    "all": [                      // every child must be true
      { "indicator": "rsi", "period": 14, "operator": "crossesAbove", "value": 30 },

      // compare a series to another series instead of a number
      { "indicator": "close", "operator": "greaterThan",
        "reference": { "indicator": "sma", "period": 200 } },

      // volume vs its own moving average; `period` is the averaging window
      { "indicator": "volume", "operator": "greaterThanSma", "period": 20 },

      { "any": [                  // at least one child must be true
          { "indicator": "ema", "period": 50, "operator": "greaterThan", "value": 100 },
          { "not":                // exactly one child, negated
            { "indicator": "atr", "period": 14, "operator": "greaterThan", "value": 5 } }
      ]}
    ]
  },

  "exit": {                       // REQUIRED. a condition tree, same shapes
    "any": [
      { "type": "takeProfitPercent", "value": 4 },   // optional on its own
      { "type": "stopLossPercent",   "value": 2 }    // required by riskPercent sizing
    ]
  },

  "sizing": {                     // REQUIRED
    "type": "riskPercent",        // the only type today
    "riskPercent": 1              // > 0 and <= 100
  }
}
```

## `market`

| Field | Type | Required | Bounds / notes |
|---|---|---|---|
| `exchange` | enum | yes | `binance` only. Anything else is a `422`. |
| `marketType` | enum | yes | `spot` only. |
| `symbols` | string[] | yes | 1–8. Written the human way (`SOL/USDT`); the engine derives `SOLUSDT.BINANCE` from it. |
| `timeframe` | enum | yes | `1m`, `5m`, `15m`, `1h`, `4h`, `1d`. |

**`market` does not choose what actually trades.** The instrument and bar come
from the request's top-level `instrumentId` and `barType`. Keep `timeframe` and
`barType` in step by hand (`"15m"` ↔ `...-15-MINUTE-...`) — nothing cross-checks
them, and a mismatch is a strategy reading one series while claiming another.

## Condition trees

`entry` and `exit` are each **one node**. A node is a group or a leaf:

| Shape | Meaning | Children |
|---|---|---|
| `{"all": [...]}` | every child true | 1+ (empty is an error) |
| `{"any": [...]}` | at least one true | 1+ (empty is an error) |
| `{"not": {...}}` | negation | exactly one node |
| `{"indicator": ...}` | an indicator comparison | leaf |
| `{"type": ...}` | an exit condition | leaf |

Groups nest freely, up to **5 levels deep** and **32 leaves** per tree
(`MAX_DEPTH`, `MAX_LEAVES`). Past either, the spec is rejected.

A single leaf is a valid tree — `"entry": {"indicator": "rsi", ...}` needs no
wrapping group.

## Indicator conditions

```jsonc
{ "indicator": "rsi", "period": 14, "operator": "crossesAbove", "value": 30 }
```

| Field | Required | Notes |
|---|---|---|
| `indicator` | yes | `rsi`, `sma`, `ema`, `atr`, `close`, `volume`. |
| `period` | depends | Required for `rsi`/`sma`/`ema`/`atr` (2–1000). Not allowed on `close`. On `volume`, only for the `...Sma` operators. |
| `operator` | yes | See the table below. |
| `value` | **either** | A fixed threshold. |
| `reference` | **or** | Another series. Exactly one of `value`/`reference` — both is `AMBIGUOUS_COMPARISON`, neither is `MISSING_THRESHOLD`. |

**Which operators each indicator accepts:**

| Indicator | `period` | Allowed operators |
|---|---|---|
| `rsi` | required, 2–1000 | `crossesAbove`, `crossesBelow`, `greaterThan`, `lessThan` |
| `sma` | required, 2–1000 | same four |
| `ema` | required, 2–1000 | same four |
| `atr` | required, 2–1000 | same four |
| `close` | **not allowed** | same four |
| `volume` | only with `...Sma` | `greaterThan`, `lessThan`, `greaterThanSma`, `lessThanSma` |

Volume gets a different set on purpose: it is spiky rather than continuous, so
a "crossing" of it means nothing, while comparison against its own average
does.

Two measured corrections worth knowing, both baked in: **`rsi` is on 0–100**
(Nautilus reports 0–1 internally, D7), and it uses **Wilder smoothing**, not
Nautilus's exponential default — the two differ by up to 34 points on real data
(D13). So `"value": 30` means what you think it means.

## `reference` — comparing two series

```jsonc
{ "indicator": "close", "operator": "crossesAbove",
  "reference": { "indicator": "sma", "period": 200 } }
```

| Field | Required | Notes |
|---|---|---|
| `indicator` | yes | `rsi`, `sma`, `ema`, `atr`, `close`, `volume`. |
| `period` | depends | Required for `rsi`/`sma`/`ema`/`atr`. **Forbidden** for `close`/`volume` — they come off the bar and have no window. |

This is what makes the crossover family expressible. Note it cannot be combined
with `greaterThanSma`/`lessThanSma`, which already compare against an average.

## Exit conditions

| Type | `value` | Bounds |
|---|---|---|
| `takeProfitPercent` | required | > 0 and ≤ 1000 |
| `stopLossPercent` | required | > 0 and < 100 |

These measure an open position's PnL, so they belong in `exit`. One in `entry`
is `EXIT_CONDITION_IN_ENTRY` — there is no position yet to measure.

They can sit inside `any`/`all`/`not` like any other leaf, and `exit` may also
contain indicator conditions (e.g. exit when RSI crosses back above 70).

## `sizing`

| Field | Required | Notes |
|---|---|---|
| `type` | yes | `riskPercent` — the only one implemented. |
| `riskPercent` | yes | > 0, ≤ 100. Percent of equity risked per trade. |

Size = (equity × riskPercent) ÷ stop distance. **So `riskPercent` makes a
`stopLossPercent` mandatory** — without one there is nothing to divide by, and
the spec is rejected with `MISSING_STOP_LOSS`.

## The semantic rules

Schema errors (wrong type, unknown field) come back one at a time from
pydantic. These come back as a **list**, so you can fix them in one pass:

| Code | Triggered by |
|---|---|
| `EMPTY_CONDITION_GROUP` | `{"all": []}` — `all` of nothing is true, which fires on every bar. |
| `UNSUPPORTED_OPERATOR` | e.g. `volume` with `crossesAbove`. Lists what is supported. |
| `UNKNOWN_INDICATOR` | An indicator outside the six. |
| `MISSING_THRESHOLD` | An operator with neither `value` nor `reference`. |
| `MISSING_PERIOD` | `greaterThanSma`/`lessThanSma` without a `period` to average over. |
| `AMBIGUOUS_COMPARISON` | Both `value` and `reference`; or a `...Sma` operator plus a `reference`. |
| `INVALID_REFERENCE` | A reference to `sma` with no period, or to `close`/`volume` **with** one. |
| `DUPLICATE_CONDITION` | The identical condition stated twice in the same tree. |
| `EXIT_CONDITION_IN_ENTRY` | A take-profit or stop-loss in `entry`. |
| `MISSING_STOP_LOSS` | `riskPercent` sizing with no `stopLossPercent` in `exit`. |
| `INDICATOR_PERIOD_TOO_LARGE` | Warmup exceeds the bars in the window — **backtest only**, since only it knows the window. `sma(200)` needs 200 bars before it says anything. |
| `SYMBOL_NOT_IN_CATALOG` | The symbol isn't in the catalog or at the venue — **backtest only**; the live path runs no catalog check. |

Rejected as a list:

```jsonc
{"errors": [
  {"path": "entry.all[0].value", "code": "MISSING_THRESHOLD", "message": "..."},
  {"path": "exit", "code": "MISSING_STOP_LOSS", "message": "..."}
]}
```

---

# Part 2 — `POST /v1/backtests`

**Everything here is camelCase, including inside `fees`.**

```jsonc
{
  "requestId": "req_sol_demo_0001",        // REQUIRED. 1-128. Idempotency key:
                                           //   same id + same body  -> the existing job
                                           //   same id + different body -> 409 REQUEST_ID_CONFLICT
  "strategyVersionId": "sv_sol_demo_0001", // REQUIRED. 1-128. Your identifier for this version
  "spec": { /* Part 1 */ },                // REQUIRED

  "venue": "BINANCE",                      // REQUIRED. 1-32
  "instrumentId": "SOLUSDT.BINANCE",       // REQUIRED. 1-64. What actually trades
  "barType": "SOLUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL",  // REQUIRED. 1-128

  "start": "2024-01-01T00:00:00Z",         // REQUIRED. MUST carry a timezone
  "end":   "2024-03-01T00:00:00Z",         // REQUIRED. MUST be after start
  "startingBalances": ["10000 USDT"],      // REQUIRED. 1-8 entries, "<amount> <currency>"

  "fees": {                                // REQUIRED as a whole
    "makerBps": "1",                       // REQUIRED. 0-10000
    "takerBps": "10"                       // REQUIRED. 0-10000
  },
  "slippageBps": "5"                       // REQUIRED, top level. 0-10000
}
```

| Field | Required | Notes |
|---|---|---|
| `requestId` | yes | Resubmitting the same id with the same payload returns the existing job rather than running twice. With a *different* payload it is a `409` — an id means one thing. |
| `strategyVersionId` | yes | Opaque to the engine; it travels into the stored result. |
| `spec` | yes | Part 1. Validated with the window and the catalog, so warmup and symbol checks apply here. |
| `venue`, `instrumentId`, `barType` | yes | The instrument actually backtested. |
| `start` / `end` | yes | **Timezone required.** A naive timestamp would mean a different window on a different machine, and the result would not be reproducible. `end` must be strictly after `start`. |
| `startingBalances` | yes | 1–8 strings like `"10000 USDT"`. |
| `fees.makerBps` / `takerBps` | **yes** | No default. Omitting either is a `422`, never a zero — a backtest at zero cost produces the fantasy numbers this platform exists to refute. Zero is allowed if you actually mean it. |
| `slippageBps` | **yes** | Same rule. Sits at the top level here, *not* inside `fees`. |

Returns `202` and `{"jobId": "...", "status": "..."}`. A replay of the same
`requestId` with the same payload returns **`200`** and the existing job
instead — the status code is how you tell a new run from a replay. Poll
`GET /v1/backtests/{jobId}`; cancel with `DELETE /v1/backtests/{jobId}` while
it is still queued.

One nuance on `SYMBOL_NOT_IN_CATALOG`: the check is *knowable*, not *already
ingested*. The worker fetches what the catalog is missing, so a symbol the
venue lists is a valid request even against a cold catalog. Only a symbol
nobody can produce data for is rejected.

---

# Part 3 — `PUT /v1/live/{account_id}`

**camelCase throughout**, nested objects included — the same as the backtest
contract. snake_case is still accepted on every field, so a caller written
against the older shape keeps working, but camelCase is the spelling to write.

```jsonc
// PUT /v1/live/acct_sol_demo      <- the account id lives in the URL
{
  "spec": { /* Part 1, unchanged from the backtest */ },   // REQUIRED
  "strategyVersionId": "sv_sol_demo_0001",                 // REQUIRED. 1-128
  "venue": "BINANCE",                                      // REQUIRED. 1-32
  "instrumentId": "SOLUSDT.BINANCE",                       // REQUIRED. 1-64
  "barType": "SOLUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL",    // REQUIRED. 1-128

  "mode": "SIMULATION",        // optional, defaults to SIMULATION. SIMULATION | LIVE
  "credentialRef": null,       // optional; REQUIRED when mode is LIVE.
                               //   A POINTER to a key, never a key. Omit for SIMULATION.
                               //   Never echoed back in any response.

  "risk": {                    // OPTIONAL as a whole. Absent = unlimited.
                               //   Any subset; omitted ones are unlimited.
    "maxOrderNotional":    "2000",   // optional, > 0
    "maxPositionNotional": "5000",   // optional, > 0
    "maxOpenPositions":     1,       // optional, integer >= 1
    "dailyLossLimit":      "300"     // optional, > 0
  },

  "fees": {                    // REQUIRED as a whole
    "makerBps":    "1",        // REQUIRED. 0-10000
    "takerBps":   "10",        // REQUIRED. 0-10000
    "slippageBps": "5"         // REQUIRED. 0-10000  <- lives INSIDE fees here
  }
}
```

| Field | Required | Notes |
|---|---|---|
| `{account_id}` (URL) | yes | 1–128 chars. The unit of risk, credentials and reconciliation — one node per account. Writing twice leaves one account, not two nodes. |
| `spec` | yes | Identical to the backtest's. Validated **without** the catalog or a window, so no `SYMBOL_NOT_IN_CATALOG` and no warmup check here. |
| `mode` | no → `SIMULATION` | `SIMULATION` = live feed, simulated fills, no key, no money. `LIVE` is accepted by the API and then refused by the supervisor (ADR-001), surfacing as `observed.status: FAILED`. |
| `credentialRef` | only for `LIVE` | `LIVE` without one is a `422` (`MISSING_CREDENTIAL_REF`). A secret in this field would reach the request log, the stored record and every backup of it. |
| `risk` | no | Omit for unlimited — a choice, not a safe default. Overridden entirely by a mandate's `limits` once one exists. |
| `fees` | **yes** | Same no-defaults rule as the backtest, for a stronger reason: a simulation with no fees is a marketing number someone may act on. Sizing uses `takerBps + slippageBps`, matching the backtest builder exactly — different numbers make the two runs incomparable. |

**Not accepted here** (all `422` as unknown fields): `requestId`, `start`,
`end`, `startingBalances`. Live has no window, and a simulated account's
balance is fixed at `10_000 USDT` in code — deliberately not tunable, since a
simulation's balance is not a number anyone should adjust to make a result look
better.

Returns `200` and the stored record — meaning **recorded**, not running. Watch
`GET /v1/live/{account_id}` until `observed.status` is `RUNNING` with
`observed.revision` matching `desired.revision`.

---

# Part 4 — the mandate bodies

Also inputs, on the same account. Full behaviour in
[`live-api.md`](live-api.md).

**`PUT /v1/live/{account_id}/mandate`** — grant authority:

```jsonc
{
  "mandateId": "m_1",             // REQUIRED. 1-128
  "issuedBy": "trading-core",     // REQUIRED. 1-128, free text, lands in every audit line
  "limits": {                     // optional. same four keys as `risk`
    "maxOrderNotional": "5000"
  },
  "instruments": ["SOLUSDT.BINANCE"]  // optional, <= 64. Empty/absent = every instrument
}
```

There is **no expiry field**; sending one is a `422`. A mandate lives until
revoked, because a TTL is an outage dependency wearing a schedule.

**`DELETE /v1/live/{account_id}/mandate`** — revoke. Note this DELETE **takes a
body**, which most clients won't send without being told to:

```jsonc
{
  "revokedBy": "an operator",     // REQUIRED. 1-128
  "reason": "drawdown"            // optional, <= 512
}
```

---

# Part 5 — casing

**Requests are camelCase, everywhere, on both endpoints.** Nested objects
included. That is the whole rule now.

```jsonc
"fees": { "makerBps": "1", "takerBps": "10", "slippageBps": "5" }   // backtest AND live
"risk": { "maxOrderNotional": "2000" }
"limits": { "maxOrderNotional": "5000" }
```

It was not always so. `risk` and `fees` on the live route used to be the only
snake_case objects on an otherwise camelCase surface, because they are the
*storage* models from `live/desired_state.py` reused as the wire schema, and
they had no alias generator. `makerBps` inside `fees` was a `422` while
`strategyVersionId` beside it was fine. They now inherit `WireModel`, which
carries the alias generator the backtest contract always had.

**snake_case still works**, on every field of both endpoints — `populate_by_name`
is on, and records already written to Redis with field names have to keep
reading back. So a caller mid-migration is never broken by this. Prefer
camelCase in anything new.

**Responses are still snake_case** (except `leaseHolder`, `accountId`,
`killSwitch`). Accepting camelCase on the way in is additive; renaming what
comes back is a migration with `api-control` on the other side of it, and that
has not happened.

Moving a backtest body to live is therefore **one edit to `fees`**: top-level
`slippageBps` moves inside the `fees` object. `makerBps` and `takerBps` stay
exactly as they are.

# Part 6 — what a rejection looks like

| Status | Shape | When |
|---|---|---|
| `401` | `{"code": "UNAUTHENTICATED", ...}` | Missing or wrong bearer token. |
| `409` | `{"code": "REQUEST_ID_CONFLICT", ...}` | Backtest only: same `requestId`, different payload. |
| `422` | `{"errors": [...]}` | Semantic spec problems — the whole list at once. |
| `422` | pydantic detail | Structural problems: unknown field, wrong type, out of bounds. |

Callers branch on `code`, never on the message text. See
[`error-handling.md`](error-handling.md).

# Reading further

- `src/engine/dsl/schema.py` — the spec, every model.
- `src/engine/dsl/indicators.py` — the indicator registry and operator sets.
- `src/engine/dsl/validator.py` — every semantic rule, with its code.
- `src/engine/backtest/request.py` — the backtest contract.
- `src/engine/api/routes/live.py` — the live contract.
- [`live-api.md`](live-api.md) — what the live endpoints *do*, and the lifecycle.
