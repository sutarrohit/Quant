# The live control plane, endpoint by endpoint

For a developer about to call `/v1/live` from `api-control`, or wondering why
there is no sandbox API. Routes live in `src/engine/api/routes/live.py`.

## The one thing to understand first

**These routes do not start anything.** A backtest is a request that runs and
finishes; live is a *state* that should still be true after a deploy, a crash,
or the API restarting. So `PUT` records what an account *should* be doing, and
the supervisor (`engine.live.main`) converges on it. Restarting the API changes
nothing about what is trading.

Two consequences that surprise people:

* the resource is keyed by **account**, not by request. Writing the same intent
  twice leaves one account, not two nodes trading it;
* a `200` from `PUT` means *recorded*, not *running*. What is actually running
  comes back on `GET` as `observed`.

**There is no separate sandbox API, by design.** Sandbox/paper is
`"mode": "SIMULATION"` on these same routes — the default. The mode, the
package (`engine.simulation`) and the Nautilus value (`Environment.SANDBOX`)
all deliberately say one word, because three names for one thing is how a node
ends up declaring itself live while running a simulated exchange (D17).

## Conventions that apply to every route

| | |
|---|---|
| Auth | `Authorization: Bearer <INTERNAL_API_KEY>` on **all** routes. Missing or wrong → `401 UNAUTHENTICATED`. |
| Unknown fields | `extra="forbid"` everywhere. A typo is a `422`, never a silent default. |
| Request casing | Top-level keys are **camelCase** (`strategyVersionId`). |
| Nested casing | Also camelCase (`maxOrderNotional`, `makerBps`). snake_case is still accepted everywhere, so an older caller keeps working. |
| Response casing | **snake_case**, except `leaseHolder`, `accountId` and `killSwitch`. |
| Errors | The envelopes in [`error-handling.md`](error-handling.md). Callers branch on `code`. |

## The routes

| Method | Path | What it does |
|---|---|---|
| `PUT` | `/v1/live/{account_id}` | Record that an account should be trading this strategy |
| `GET` | `/v1/live/{account_id}` | Desired vs. observed vs. who holds the lease |
| `GET` | `/v1/live` | Every account with a record |
| `DELETE` | `/v1/live/{account_id}` | Ask it to stop signalling |
| `POST` | `/v1/live/{account_id}/kill` | Total stop, exits included |
| `DELETE` | `/v1/live/{account_id}/kill` | Release the kill switch |
| `GET` | `/v1/live/{account_id}/kill` | Is it engaged |
| `PUT` | `/v1/live/{account_id}/mandate` | Grant authority to trade, on these terms |
| `DELETE` | `/v1/live/{account_id}/mandate` | Revoke it (needs a body) |
| `GET` | `/v1/live/{account_id}/mandate` | Read it |

---

### `PUT /v1/live/{account_id}` — record desired state

Validates the spec, then writes the record and bumps its `revision`. The
supervisor restarts a node whose running revision no longer matches, which is
how a spec change takes effect.

**Path:** `account_id` — free-form, 1–128 chars. The unit of risk, credentials
and reconciliation, and therefore of process isolation: one node per account.

**Body** (`LiveRequest`, `live.py:61`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `spec` | object | yes | A `StrategySpec` — byte-identical to what a backtest takes. Semantically validated; failures come back as the `{"errors": [...]}` list. |
| `strategyVersionId` | string 1–128 | yes | Caller's identifier for the version being run. |
| `venue` | string 1–32 | yes | e.g. `BINANCE`. |
| `instrumentId` | string 1–64 | yes | e.g. `BTCUSDT.BINANCE`. |
| `barType` | string 1–128 | yes | Nautilus bar type, e.g. `BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL`. |
| `mode` | `SIMULATION` \| `LIVE` | no, default `SIMULATION` | See the gate below. |
| `credentialRef` | string ≤256, nullable | only when `mode=LIVE` | **A pointer to a key, never a key.** A secret here would reach the request log, the stored record, and every backup of it (ADR-001). Never echoed back. |
| `risk` | object | no, default unlimited | `maxOrderNotional`, `maxPositionNotional` (decimal strings, > 0), `maxOpenPositions` (int ≥ 1), `dailyLossLimit` (decimal string, > 0). Account-level, not per strategy: five strategies that are all long-BTC-momentum are one bet at five times the size. |
| `fees` | object | **yes** | `makerBps`, `takerBps`, `slippageBps` — decimal strings, 0–10000. Omitted is a `422`, never a zero. The venue cannot supply it (public instrument data reports zero fees, real rates need a key), so the operator declares it (D20). Zero is allowed, but must be said. |

```jsonc
// PUT /v1/live/acct_1
{
  "spec": { /* StrategySpec */ },
  "strategyVersionId": "sv_1",
  "venue": "BINANCE",
  "instrumentId": "BTCUSDT.BINANCE",
  "barType": "BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL",
  "mode": "SIMULATION",
  "risk": { "maxOrderNotional": "5000" },
  "fees": { "makerBps": "1", "takerBps": "10", "slippageBps": "5" }
}
```

**Returns** `200` and the stored record: `account_id`, `venue`,
`instrument_id`, `bar_type`, `spec`, `strategy_version_id`, `spec_hash`,
`mode`, `risk`, `fees`, `status` (`RUNNING`), `revision`, `updated_at`.
`credential_ref` is stripped — even a reference is not handed back by default.

**Errors:** `422` with the `{"errors": [...]}` list for an invalid spec, for an
unknown field, for a malformed limit or fee, and for `mode=LIVE` without a
`credentialRef` (`MISSING_CREDENTIAL_REF`).

**The live gate.** A `mode=LIVE` request with a `credentialRef` is *accepted*
here — `200`. The refusal happens later, in the supervisor:
`build_node_config` raises `LiveNotPermitted` (`live/node.py:110`) because
ADR-001's conditions are unmet. It is caught by the supervisor's generic branch
(`supervisor.py:282`), so it surfaces on `GET` as
`observed.status = "FAILED"` with `error.code = "LiveNotPermitted"` — the class
name, not the `LIVE_NOT_PERMITTED` code, since that branch uses
`type(exc).__name__`. `SIMULATION` is the mode that actually runs today.

---

### Taking a backtest request live

The spec is the thing that carries over: **byte-identical JSON, same
`DslStrategy`, same config factory.** Everything around it changes, because a
backtest is a request with a window and live is a state with none.

`POST /v1/backtests` (`backtest/request.py`) against
`PUT /v1/live/{account_id}` (`api/routes/live.py:61`):

| Backtest field | Live | Why |
|---|---|---|
| `requestId` | **dropped** | The idempotency key becomes the `account_id` in the URL. A backtest is keyed by request; an account is keyed by itself, so writing twice leaves one account rather than two nodes trading it. |
| `strategyVersionId` | same | |
| `spec` | **same** | Unchanged, down to the byte. |
| `venue`, `instrumentId`, `barType` | same | |
| `start`, `end` | **dropped** | Live has no window. It runs until stopped. |
| `startingBalances` | **dropped** | Not yours to set. A simulated account starts with a fixed `10_000 USDT` (`simulation/node.py:41`) — deliberately not configurable, because a simulation's balance is not a number anyone should be tuning to make a result look better. In `LIVE` the venue supplies it. |
| `fees.makerBps` | `fees.makerBps` | Unchanged. |
| `fees.takerBps` | `fees.takerBps` | Unchanged. |
| `slippageBps` (top level) | `fees.slippageBps` (**moves inside** `fees`) | One object for everything a fill costs. `cost_bps` = taker + slippage, matching `backtest/builder.py` exactly — sized one way in backtest and another in simulation, the two would not be comparable. |
| — | `mode` | New. `SIMULATION` (default) or `LIVE`. |
| — | `credentialRef` | New. Required only for `LIVE`. |
| — | `risk` | New. No backtest equivalent: a backtest cannot lose money, so it needs no limits. |

So the request at the top becomes:

```jsonc
// PUT /v1/live/acct_sol_demo
{
  "spec": {
    "strategyId": "sol-rsi-recovery",
    "version": 1,
    "market": {
      "exchange": "binance",
      "marketType": "spot",
      "symbols": ["SOL/USDT"],
      "timeframe": "15m"
    },
    "entry": {
      "all": [
        { "indicator": "rsi", "period": 14, "operator": "crossesAbove", "value": 30 }
      ]
    },
    "exit": {
      "any": [
        { "type": "takeProfitPercent", "value": 4 },
        { "type": "stopLossPercent", "value": 2 }
      ]
    },
    "sizing": { "type": "riskPercent", "riskPercent": 1 }
  },
  "strategyVersionId": "sv_sol_demo_0001",
  "venue": "BINANCE",
  "instrumentId": "SOLUSDT.BINANCE",
  "barType": "SOLUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL",
  "mode": "SIMULATION",
  "risk": {
    "maxOrderNotional": "2000",
    "maxPositionNotional": "5000",
    "maxOpenPositions": 1,
    "dailyLossLimit": "300"
  },
  "fees": {
    "makerBps": "1",
    "takerBps": "10",
    "slippageBps": "5"
  }
}
```

`risk` is optional — omit it and the account is unlimited, which is a choice
rather than a default worth relying on. Everything else above is required.

```bash
curl -X PUT http://localhost:8000/v1/live/acct_sol_demo \
  -H "Authorization: Bearer $INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  --data @live-sol.json
```

**Two things nothing checks for you.**

`spec.market` is informational on both paths: the instrument actually traded
comes from the top-level `instrumentId` and `barType`. `"timeframe": "15m"` and
`...-15-MINUTE-...` have to be kept in step by hand, and a mismatch is a
strategy reading one series while claiming another. The live path also calls
`validate_spec` without `known_instruments`, so there is no catalog check
here — an instrument Binance does not list fails later, at node start.

**Then watch it, don't assume it.** The `200` means recorded. The supervisor
(`uv run python -m engine.live.main`) and both Redis instances have to be up
for anything to run, and the answer is on `GET /v1/live/acct_sol_demo`:
`observed.status` reaching `RUNNING` with `observed.revision` matching
`desired.revision`. Unlike a backtest, the first bar arrives when the venue
sends one — on a 15-minute bar type, up to fifteen minutes of a node that is
running and has done nothing yet.

---

### `GET /v1/live/{account_id}` — what should be, and what is

```jsonc
{
  "desired":  { /* as returned by PUT */ },
  "observed": {
    "account_id": "acct_1",
    "status": "RUNNING",        // STARTING | RECONCILING | RUNNING | STOPPED | FAILED | HALTED
    "revision": 3,              // which desired revision is actually running
    "started_at": "...", "heartbeat_at": "...",
    "error": null
  },
  "leaseHolder": "supervisor-1"  // null if nobody holds it
}
```

`observed` is `null` until a supervisor has seen the account. `HALTED` is the
one status the supervisor will not clear by itself — it means the node
disagreed with the venue about money, and an operator clears it by re-stating
the desired state, which bumps the revision.

**Errors:** `404 ACCOUNT_NOT_FOUND`.

### `GET /v1/live` — list

No input. Returns `{"accounts": ["acct_1", "acct_2"]}`, sorted.

---

### `DELETE /v1/live/{account_id}` — stop

No body. Sets `status` to `STOPPED` and bumps the revision; returns the record.

The record is **kept, not deleted** — the supervisor still has to act on it,
and a deleted row is indistinguishable from one that was never written.
Stopping does **not** close an open position: turning an infrastructure action
into a realised loss should never be implicit.

**Errors:** `404 ACCOUNT_NOT_FOUND`.

---

### The kill switch — `POST` / `DELETE` / `GET /v1/live/{account_id}/kill`

No body on any of them. All return
`{"accountId": "acct_1", "killSwitch": "ENGAGED" | "RELEASED"}`.

Stops the account submitting new orders, immediately. Three things worth
knowing:

* **It does not require an existing account.** Killing `never_seen` is a `200`.
  Deliberate: an operator must be able to stop a node when the service that
  sets policy is unreachable, which is exactly when they most want to
  (ADR-001). It touches Redis directly, not `api-control`.
* **It is a total stop, exits included.** You reach for a kill switch when you
  do not trust the strategy, and a strategy you do not trust should not be
  closing positions either — its idea of an exit may be the bug. The position
  becomes yours to close at the exchange.
* **It does not flatten.** Again a different decision, and it has no verb here.

---

### Mandates (ADR-002)

Authority to trade, held ahead of time rather than asked for at order time —
because a `trading-core` outage must not stop trading, and a node that has to
ask permission stops exactly when the thing it asks is unreachable. A live node
refuses to start without an active mandate; **simulation does not need one**,
though it applies one if it happens to exist (`worker.py:271`).

#### `PUT /{account_id}/mandate` — grant

| Field | Type | Required | Notes |
|---|---|---|---|
| `mandateId` | string 1–128 | yes | Identifies this grant. Changes when the terms change, so a node can say which mandate an order was placed under. |
| `issuedBy` | string 1–128 | yes | Free text; it belongs in every audit line. |
| `limits` | object | no | Same shape as `risk` above. Once a mandate exists, these are the single source. |
| `instruments` | string[] ≤64 | no | Empty means every instrument this account is configured to trade. |

A `PUT` because authority is a state, not an event: granting twice leaves one
mandate. **There is no expiry field** — passing `expiresAt` is a `422`. ADR-002
chose revoke-only, because a TTL is an outage dependency wearing a schedule: a
mandate that lapses during a `trading-core` outage stops trading, the exact
outcome the decision exists to prevent. Re-granting is also how a revoked
account is authorised again, so the record of what was withdrawn is not edited
away.

Returns the mandate: `account_id`, `mandate_id`, `issued_by`, `issued_at`,
`limits`, `instruments`, `revoked_at`, `revoked_by`, `revoked_reason`.

#### `DELETE /{account_id}/mandate` — revoke

**Takes a body**, which most HTTP clients will not send on a `DELETE` without
being told to (`requests`/`httpx`: use `client.request("DELETE", ..., json=...)`).

| Field | Type | Required |
|---|---|---|
| `revokedBy` | string 1–128 | yes |
| `reason` | string ≤512 | no |

The account stops opening new positions; **exits keep running**, because
flattening on revoke would turn a control-plane action into a market one at
whatever price happens to be there. Takes effect on the node's next mandate
read, within seconds — nothing is pushed, so a `trading-core` that cannot reach
this store cannot stop an account. That is the cost ADR-002 states, and the
kill switch is what covers it.

**Errors:** `404 ACCOUNT_NOT_FOUND` when there is no mandate to revoke.

#### `GET /{account_id}/mandate`

No input. `404 ACCOUNT_NOT_FOUND` if none.

---

## Three ways to stop an account, and how to pick

| | `DELETE /{id}` | `DELETE /{id}/mandate` | `POST /{id}/kill` |
|---|---|---|---|
| New entries | stop | stop | stop |
| Exits, stops, take-profits | stop (node shuts down) | **keep running** | stop |
| Open position | left open | managed by the strategy | **yours to close at the venue** |
| Needs an existing record | yes | yes | **no** |
| Depends on `api-control` | yes | yes | **no** |
| Reach for it when | the strategy is done | the strategy may not take new risk | you do not trust the strategy |

None of them flatten. That is a fourth decision and it has no endpoint.

## Error codes you can get back here

| Code | Status | When |
|---|---|---|
| `UNAUTHENTICATED` | 401 | Missing or wrong bearer token, any route. |
| `ACCOUNT_NOT_FOUND` | 404 | No desired state, or no mandate, for that account. |
| *(spec error list)* | 422 | Invalid spec, unknown field, bad limit or fee, `LIVE` without `credentialRef`. |
| `LIVE_NOT_PERMITTED` | 409 | Never from these routes — raised in the supervisor, read off `observed.error`. |

## Reading further

- `src/engine/api/routes/live.py` — the routes, with the reasoning inline.
- `src/engine/live/desired_state.py` — `DesiredState`, `ObservedState`, the store.
- `src/engine/live/mandate.py` — mandates, and what revocation does not do.
- `tests/live/test_live_routes.py` — every shape above, asserted.
- `docs/adr-001-live-execution.md` — why `LIVE` is gated.
- `docs/adr-002-risk-kernel.md` — mandates, and the outage they are shaped by.
- `docs/runbook-live.md` — what an operator does when this path fails.
