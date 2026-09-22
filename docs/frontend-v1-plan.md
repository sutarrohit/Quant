# Frontend v1 — plan for review

**Status:** proposal, not built. Written 2026-09-22 against the code on `main` (`0b232e5`).

## The answer first

Three services already exist and each one is doing its job. What is missing is the
**middle layer**: `apps/server` has no strategy, backtest or simulation routes at all, so
`apps/web` has nothing to call. Roughly 80% of the work in this plan is in `apps/server`,
15% in `apps/web`, and **one blocking change in `packages/engine_server`** (an endpoint that
serves the equity curve and trade rows — they exist only as Parquet on the engine's disk today).

The v1 the user gets: **author a strategy → run a backtest → read the result → promote it to a
paper simulation → watch it → stop or kill it.** No AI, no marketplace, no live money (the
engine refuses real-money mode by design — ADR-001).

---

# 1. What exists today

Verified by reading the code, not assumed.

| Piece | Where | State |
|---|---|---|
| **Engine** | `packages/engine_server` (FastAPI, `:8000`) | Backtests + paper/live control plane, working. No CORS, one bearer token, no concept of a user. |
| **Main API** | `apps/server` (Hono, `:4000`) | Privy auth, user + wallet routes only. **No engine client, no quant routes.** |
| **Web** | `apps/web` (Next 16, `:3000`) | Privy login, a protected `/dashboard` stub, full shadcn UI kit, `recharts`. |
| **Postgres** | `packages/prisma` | `User` and `Wallet` only. **No strategy/backtest tables.** |

## The request path, as already wired

```text
browser  ──same-origin──>  Next.js :3000
                             │  rewrites /api/v1/* (next.config.ts)
                             ▼
                           Hono  :4000   ← requireAuth verifies the privy-token
                             │  (to build)  Authorization: Bearer NT_INTERNAL_API_KEY
                             ▼
                           FastAPI :8000  ← arq worker, Redis, Parquet catalog
```

Two properties this already buys us, and both should be preserved:

- The browser **only ever talks to the Next origin**. The `privy-token` cookie is same-origin,
  there is no CORS on the hot path, and the engine's address never ships in the bundle.
- The engine is **not internet-reachable**. Its bearer token lives only in `apps/server`'s env.
  The browser must never see it, and no route may forward a client-supplied engine path.

## Engine surface the frontend needs

All of these require `Authorization: Bearer <NT_INTERNAL_API_KEY>`.

| Call | Returns |
|---|---|
| `GET /v1/catalog/instruments` | `{instruments: [{instrumentId}], barTypes: [{barType, start, end}]}` |
| `POST /v1/backtests` | `202 {jobId, status}` — or **`200`** when the `requestId` is a replay |
| `GET /v1/backtests/{jobId}` | `{jobId, status, submittedAt, startedAt, finishedAt, error, result}` |
| `DELETE /v1/backtests/{jobId}` | same shape; only cancellable while `QUEUED` |
| `PUT /v1/live/{accountId}` | the stored desired state (`credential_ref` stripped) |
| `GET /v1/live/{accountId}` | `{desired, observed, leaseHolder}` |
| `GET /v1/live` | **every account on the box** — see §7, never proxy this |
| `DELETE /v1/live/{accountId}` | stop signalling (does *not* close the position) |
| `POST\|DELETE\|GET /v1/live/{accountId}/kill` | the kill switch — a total stop, exits included |
| `PUT\|DELETE\|GET /v1/live/{accountId}/mandate` | authority to trade (ADR-002) |
| `GET /health`, `GET /ready` | unauthenticated liveness / readiness |

**Job statuses:** `QUEUED` → `FETCHING_DATA` → `RUNNING` → `SUCCEEDED` \| `FAILED` \| `CANCELLED`.
`FETCHING_DATA` is its own state on purpose — a cold two-year window is minutes of paging against
Binance, and the UI should say "downloading history", not "computing".

**A successful job's `result`:**

```jsonc
{
  "fills": 94, "positions": 47, "closedPositions": 47,
  "realizedPnl": "-733.11", "totalCommission": "618.73",
  "summary": { /* 19 keys, every money/ratio value a STRING */ },
  "artifacts": { "jobId": "...", "trades": "<path>", "equityCurve": "<path>", "summary": "<path>" },
  "published": false
}
```

`summary` keys: `startingEquity`, `endingEquity`, `totalReturn`, `cagr`, `maxDrawdown`, `sharpe`,
`sortino`, `winRate`, `profitFactor`, `tradeCount`, `averageTrade`, `medianTrade`,
`averageHoldingSeconds`, `totalFees`, `totalSlippage`, `exposurePercent`, `unrealizedPnl`,
`openPositions`.

---

# 2. Decisions this plan makes

Each one is a fork in the road; flag any you disagree with before I build.

### D1 — `apps/server` owns the durable record; the engine's Redis is a cache

Engine job records expire after **7 days** (`NT_JOB_TTL_SECONDS`) and hold no user identity.
So every backtest a user starts gets a **Postgres row first**, and the engine job id is a column
on it. A user's history survives a Redis flush, and authorization is a query on our own table
rather than a question the engine cannot answer.

### D2 — The client never names an engine resource

The browser sends **our** ids (`runId`, `simulationId`). `apps/server` maps them to `jobId` /
`accountId` after checking ownership. A route that took a `jobId` from the client would let any
authenticated user read any other user's backtest, because the engine has no idea who is asking.

### D3 — `accountId` is minted by the server, never accepted

`PUT /v1/live/{accountId}` creates whatever account you name. The account is the unit of risk,
credentials and reconciliation. So the id is generated server-side as
`acct_<uuid-hex>` and stored on the `Simulation` row — **the string never appears in a request
body or a URL the client controls.**

### D4 — Poll, don't push, for v1

The engine can POST finished results to `NT_API_CONTROL_URL` + `/internal/backtest-results`
(`store/publish.py`, already built and tested, inert until configured). I am **not** wiring it in
v1:

- polling works today with zero new moving parts, and the job record is authoritative anyway;
- the webhook is fire-and-forget by design — a publish failure never fails the job — so it can
  never be the only path and we would need the poller regardless.

The browser polls `GET /api/v1/backtests/:runId` every 2s while non-terminal; that handler reads
the engine, **writes the terminal result into Postgres**, and returns it. Add the webhook later as
a latency optimization, not as a correctness one.

### D5 — Strategy versions are immutable, and the spec hash is the identity

`StrategyVersion` rows are append-only. Editing a strategy makes version N+1. This matches the
engine's own contract (specs are frozen and hashed into `strategyVersionId`) and is what makes a
result mean something six weeks later — spec section on determinism is worthless if the spec
behind a stored number can be edited.

### D6 — A form builder for the DSL in v1, not a code editor

The DSL is a closed set: six indicators, six operators, two exit types, one sizing rule. A form
that can only emit valid shapes beats a JSON textarea that mostly emits `422`s. A read-only JSON
preview pane sits beside it, and an "advanced" raw-JSON mode can come later.

### D7 — Money stays a string all the way to the pixel

Every money and ratio value the engine returns is a decimal string. The frontend formats strings
and only converts to `number` **inside the chart component**, where a float is unavoidable. No
`parseFloat` in a table cell, no arithmetic in a component.

---

# 3. Scope of v1

### In

| # | Screen | Route | What it does |
|---|---|---|---|
| 1 | **Strategies** | `/strategies` | List, create, open. Version history per strategy. |
| 2 | **Strategy builder** | `/strategies/:id` | Form over the DSL + live JSON preview + inline validation errors from the engine. |
| 3 | **New backtest** | `/strategies/:id/backtest` | Instrument, bar type, window, starting balance, fees, slippage. Defaults from the catalog. |
| 4 | **Backtest run** | `/backtests/:runId` | Status timeline while running; summary tiles, equity curve, drawdown, trade table when done; error code + message when failed. |
| 5 | **Backtests** | `/backtests` | The user's runs, newest first, with status and headline return. |
| 6 | **Simulations** | `/simulations` | Paper accounts: desired vs observed, revision match, heartbeat age. |
| 7 | **Simulation detail** | `/simulations/:id` | Start / stop / kill, and the same spec that was backtested. |

### Out, deliberately

Live money (engine refuses it — ADR-001) · AI / natural-language authoring · walk-forward, Monte
Carlo, parameter sweeps · marketplace, sharing, leaderboards · mobile layouts beyond "does not
break" · multi-venue (only `binance` / `spot` exist in the DSL) · mandates UI (an operator concern
until there is a second human in the loop).

---

# 4. Postgres — what to add

New models in `packages/prisma/schema.prisma`. Follow the **quant-table convention** already
established there (`dbgenerated("gen_random_uuid()")`, snake_case `@map` on every multi-word
field) — not the `User` convention.

```prisma
model Strategy {
  id        String   @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  userId    String   @map("user_id")
  name      String
  archivedAt DateTime? @map("archived_at")
  createdAt DateTime @default(now()) @map("created_at")
  updatedAt DateTime @updatedAt @map("updated_at")
  user      User     @relation(fields: [userId], references: [id], onDelete: Cascade)
  versions  StrategyVersion[]
  @@index([userId])
  @@map("strategy")
}

// Immutable. An edit is a new row. `spec` is the engine's camelCase JSON, byte for byte --
// the same object goes to POST /v1/backtests and PUT /v1/live/{id}.
model StrategyVersion {
  id         String   @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  strategyId String   @map("strategy_id") @db.Uuid
  version    Int
  spec       Json
  specHash   String   @map("spec_hash")   // sha256 of the canonical JSON; our own, not the engine's
  createdAt  DateTime @default(now()) @map("created_at")
  strategy   Strategy @relation(fields: [strategyId], references: [id], onDelete: Cascade)
  runs       BacktestRun[]
  @@unique([strategyId, version])
  @@map("strategy_version")
}

model BacktestRun {
  id           String   @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  userId       String   @map("user_id")
  versionId    String   @map("version_id") @db.Uuid
  // The idempotency key sent to the engine. Generated once, reused on every retry of the
  // submit call, so a network failure mid-POST can never start a second run.
  requestId    String   @unique @map("request_id")
  jobId        String?  @map("job_id")            // null until the engine accepts it
  status       String                              // mirrors the engine's JobStatus
  venue        String
  instrumentId String   @map("instrument_id")
  barType      String   @map("bar_type")
  windowStart  DateTime @map("window_start")
  windowEnd    DateTime @map("window_end")
  startingBalances String[] @map("starting_balances")
  makerBps     Decimal  @db.Decimal(38, 18) @map("maker_bps")
  takerBps     Decimal  @db.Decimal(38, 18) @map("taker_bps")
  slippageBps  Decimal  @db.Decimal(38, 18) @map("slippage_bps")
  summary      Json?                               // copied on terminal SUCCEEDED
  errorCode    String?  @map("error_code")
  errorMessage String?  @map("error_message")
  submittedAt  DateTime @default(now()) @map("submitted_at")
  finishedAt   DateTime? @map("finished_at")
  user         User     @relation(fields: [userId], references: [id], onDelete: Cascade)
  version      StrategyVersion @relation(fields: [versionId], references: [id])
  @@index([userId, submittedAt])
  @@map("backtest_run")
}

model Simulation {
  id         String   @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  userId     String   @map("user_id")
  versionId  String   @map("version_id") @db.Uuid
  // D3: minted here, never accepted from a client. Unique so two simulations can never
  // collide onto one engine account.
  accountId  String   @unique @map("account_id")
  name       String
  venue      String
  instrumentId String @map("instrument_id")
  barType    String   @map("bar_type")
  makerBps   Decimal  @db.Decimal(38, 18) @map("maker_bps")
  takerBps   Decimal  @db.Decimal(38, 18) @map("taker_bps")
  slippageBps Decimal @db.Decimal(38, 18) @map("slippage_bps")
  riskLimits Json?    @map("risk_limits")
  createdAt  DateTime @default(now()) @map("created_at")
  updatedAt  DateTime @updatedAt @map("updated_at")
  user       User     @relation(fields: [userId], references: [id], onDelete: Cascade)
  version    StrategyVersion @relation(fields: [versionId], references: [id])
  @@index([userId])
  @@map("simulation")
}
```

`User` gains `strategies`, `backtests` and `simulations` back-relations.

**Not stored:** the equity curve and trade rows. They live in the engine's Parquet artifacts and
are fetched on demand (§6). Copying a 50,000-row series into Postgres to render one chart is the
wrong trade.

---

# 5. `apps/server` — the work

## 5.1 The engine client — `src/lib/engine-client.ts`

One module, the only thing in the repo that knows the engine's address. Responsibilities:

- attach `Authorization: Bearer ${env.ENGINE_INTERNAL_API_KEY}`;
- forward `x-request-id` so one id traces browser → Hono → FastAPI (the engine already honours a
  caller-supplied one and echoes it back);
- **translate the engine's error envelopes into `ApiError`**, preserving the machine-readable
  `code` and, for a `422`, the whole `errors: [...]` list;
- convert the engine's **snake_case responses** to camelCase at this boundary, so nothing above
  it has to know. (Requests are camelCase; responses are not — the engine's own
  `docs/explanations/request-reference.md` §5 says renaming responses is a migration nobody has
  done.)

New env in `src/env.ts`:

```ts
ENGINE_URL: z.url().default('http://localhost:8000'),
ENGINE_INTERNAL_API_KEY: z.string().min(1),
```

## 5.2 Two existing gaps this needs fixed first

Both are small and both block clean error handling.

1. **`onError` drops `ApiError.code`.** `src/middlewares/on-error.middleware.ts` returns
   `{statusCode, message, stack}`, while `ApiErrorSchema` in `src/types/error.ts` promises
   `{statusCode, code, message}`. The frontend must branch on codes, never message text — that is
   the engine's rule 12 and it applies here too. Fix: emit `code`, and add an optional `details`
   for the spec-error list.
2. **`ApiError` has no `details` field.** A `422` from the engine is
   `{"errors": [{path, code, message}, ...]}` and the strategy builder needs every entry to
   highlight the right field. Add `details?: unknown` to `ApiError` and carry it through `onError`.

Minor, non-blocking: the rate limiter's `keyGenerator` looks for a cookie whose name contains
`session_token`, which Privy never sets (`privy-token` / `privy-session`), so every signed-in user
shares the per-IP bucket. At 1000 requests / 10 minutes and a 2s poll, two users behind one NAT
on two running jobs are already at half the budget. Match on `privy-token` — or better, key off
`c.get('user').id`, which is available after `requireAuth`.

## 5.3 Routes

Mounted the same way `user.index.ts` is: `createRouter()`, `router.use('*', requireAuth)`,
`.openapi(route, handler)`, registered in `src/app.ts`'s `routes` array with its base path.

| Method + path | Body / notes |
|---|---|
| `GET /api/v1/catalog/instruments` | Straight pass-through of the engine's catalog, cached ~60s in-process. Powers every instrument/bar-type picker. |
| `GET /api/v1/strategies` | The user's strategies with their latest version. |
| `POST /api/v1/strategies` | `{name, spec}` → creates strategy + version 1. |
| `GET /api/v1/strategies/:id` | With version list. 404 if not the caller's. |
| `POST /api/v1/strategies/:id/versions` | `{spec}` → version N+1. |
| `POST /api/v1/strategies/validate` | `{spec}` → `{ok}` or the engine's error list. See the note below. |
| `POST /api/v1/backtests` | `{versionId, venue, instrumentId, barType, start, end, startingBalances, fees:{makerBps,takerBps}, slippageBps}`. Creates the row, mints `requestId`, submits, stores `jobId`. |
| `GET /api/v1/backtests` | The user's runs, paginated. |
| `GET /api/v1/backtests/:runId` | Reads the engine when non-terminal, persists on terminal, returns the merged view. |
| `DELETE /api/v1/backtests/:runId` | Cancel while `QUEUED`. |
| `GET /api/v1/backtests/:runId/equity` | Equity + drawdown rows. **Needs §6.** |
| `GET /api/v1/backtests/:runId/trades` | Trade rows, paginated. **Needs §6.** |
| `GET /api/v1/simulations` | The user's simulations, each enriched with the engine's `desired`/`observed`. |
| `POST /api/v1/simulations` | `{versionId, name, venue, instrumentId, barType, fees, risk?}` → mints `accountId`, `PUT`s the engine, stores the row. |
| `GET /api/v1/simulations/:id` | `{simulation, desired, observed, leaseHolder, killSwitch}`. |
| `DELETE /api/v1/simulations/:id` | Stop. Copy says plainly: **stops signalling, does not close the position.** |
| `POST /api/v1/simulations/:id/kill` | Engage. Confirmation dialog required — it is a total stop, exits included. |
| `DELETE /api/v1/simulations/:id/kill` | Release. |

**On `POST /strategies/validate`:** the engine has no standalone validate endpoint. The cheapest
honest way to get real validation is to submit a backtest and let it fail on the spec — but that
costs a queue round trip and burns a `requestId`. Two options, and I want your call
(§10, Q1): (a) mirror the ~12 semantic rules in a Zod schema in `apps/server` and accept that two
validators can drift; or (b) ask for a `POST /v1/specs/validate` on the engine, which is ~20 lines
over the `validate_spec` function that already exists. **I recommend (b)** — the DSL's whole point
is that one validator is authoritative.

## 5.4 Two contract details that will bite

- **`slippageBps` moves.** Backtest: top level, beside `fees`. Live: **inside** `fees`. Same
  numbers, different nesting. The UI collects it once; the two mappers differ by that one line.
- **Replay is a status code, not a field.** `POST /v1/backtests` answers `202` for a new job and
  `200` for a replay of the same `requestId`. Do not treat `200` as an error, and do not retry a
  submit with a fresh `requestId` — that is how one click becomes two runs.

---

# 6. The blocking engine change

**The equity curve and trade rows are not reachable over HTTP.** The worker writes them to
Parquet under `NT_ARTIFACT_PATH` and the job record carries only *paths*. `ArtifactStore.read_rows`
exists (`src/engine/store/artifacts.py:117`) but no route calls it — I grepped
`src/engine/api/` and there is no mention of artifacts at all.

Without this, backtest results in v1 are a table of 19 numbers and nothing to look at. The equity
curve is the single most valuable thing on the screen.

**Proposed** (engine side, small, and in keeping with its existing shape):

```text
GET /v1/backtests/{job_id}/artifacts/{name}?offset=&limit=
    name ∈ {equity_curve, trades}
    → {"rows": [...], "total": 4711}
    404 JOB_NOT_FOUND · 404 NOT_FOUND when the job has no artifacts
```

Server-side paginated, because a 50,000-point curve should not cross the wire in one response —
and inlining it in the job record is explicitly against the design note in `artifacts.py`.

Three things to note:

- The name must be **validated against the closed set**, never joined into a path from the
  request. A path parameter reaching `fsspec` is a file-read primitive.
- `apps/server` downsamples the curve for the chart (LTTB or plain stride to ~1,000 points) and
  sends the trade table page by page.
- This is the **only** engine change v1 needs. Everything else is additive in TypeScript.

Until it lands, the run page can ship with summary tiles only and the chart area showing "series
coming soon" — but I would rather do the engine endpoint first; it is the smaller half of the day.

---

# 7. Security notes worth stating explicitly

- **`GET /v1/live` lists every account on the engine, across all users.** Never proxy it. The
  simulations list comes from our own table, and each row is enriched by a keyed
  `GET /v1/live/{accountId}` the server already knows the caller owns.
- **Every engine-facing handler re-checks ownership from Postgres**, not from the request. D2 and
  D3 exist because the engine trusts its caller completely — it has exactly one, and that one is
  us.
- **The engine token never leaves `apps/server`.** No route may accept an engine URL, path
  fragment or account id from the client.
- `proxy.ts` and the `(protected)` layout are **UX gates, not boundaries** — that is already
  written in both files and stays true. `requireAuth` is the boundary.
- **Never render a number the API did not compute.** Total return, win rate and drawdown all come
  from the engine's summary. A convenience calculation in a component is how the UI and the
  stored record start disagreeing.

---

# 8. `apps/web` — the work

The kit is already there: shadcn (`base-nova` style, remixicon), `sidebar.tsx`, `chart.tsx`,
`table.tsx`, `recharts`, sonner, TanStack Query. Nothing new needs installing.

## 8.1 Structure

```text
app/(protected)/
  layout.tsx                  # add the sidebar shell to the existing guard
  strategies/page.tsx         # list
  strategies/[id]/page.tsx    # builder
  strategies/[id]/backtest/page.tsx
  backtests/page.tsx
  backtests/[runId]/page.tsx
  simulations/page.tsx
  simulations/[id]/page.tsx

lib/api/
  catalog/{catalog-apis.ts,catalog-queries.ts}
  strategies/{...}
  backtests/{...}
  simulations/{...}

components/
  strategy/condition-node.tsx     # recursive: all / any / not / leaf
  strategy/spec-preview.tsx
  backtest/summary-tiles.tsx
  backtest/equity-chart.tsx
  backtest/trades-table.tsx
  simulation/state-badge.tsx
```

Follow the existing `lib/api/user/` pattern exactly — a plain `*-apis.ts` calling `request()`,
and a `*-queries.ts` exporting `queryOptions` / `mutationOptions` factories. It works, it is
already the house style, and consistency here is worth more than any improvement I could make.

## 8.2 Polling

```ts
useQuery({
  ...backtestRunQueryOptions(runId),
  refetchInterval: (q) =>
    TERMINAL.has(q.state.data?.status ?? '') ? false : 2000,
})
```

`TERMINAL = new Set(['SUCCEEDED','FAILED','CANCELLED'])`. Same shape for a simulation, on a 5s
interval, terminating on nothing — a simulation has no terminal state, so it polls while the tab
is focused and stops otherwise.

## 8.3 The strategy builder

The recursive part is one component. A node is a group (`all` / `any` / `not`) or a leaf, and the
form emits exactly the JSON in `docs/explanations/request-reference.md` Part 1.

Constraints the form should make **unreachable** rather than validate after the fact:

| Rule | How the form enforces it |
|---|---|
| `close` takes no `period` | Hide the period field when `close` is selected. |
| `volume` takes a `period` only for `…Sma` operators | Show it conditionally. |
| `volume` cannot cross | Operator list is per-indicator, not global. |
| Exactly one of `value` / `reference` | A radio: "compare to a number" vs "compare to a series". |
| Take-profit / stop-loss belong in `exit` | Those leaf types are simply absent from the entry builder. |
| `riskPercent` sizing requires a `stopLossPercent` | Block submit with an inline explanation, not a server round trip. |
| Depth ≤ 5, leaves ≤ 32 | Disable "add group" at depth 5; show `n/32`. |

Everything else — duplicate conditions, warmup longer than the window, an unknown symbol — comes
back from the engine as a `path`-tagged list and is rendered against the matching field.

## 8.4 Showing results honestly

This is the product's whole thesis (`docs/Quant-Phase.md`), so it belongs in the UI and not just
the docs:

- **Fees and slippage are always visible on a result.** `totalFees` and `totalSlippage` sit in the
  summary tiles, not in a details drawer. A number produced at zero cost is a marketing number,
  and the engine refuses to produce one — the UI should not hide the ones it did charge.
- **Say when a position was still open.** `openPositions > 0` gets a line on the result: ending
  equity includes `unrealizedPnl`, and a trend follower is usually still holding when the data
  ends.
- **Label the equity curve "realized"**, because it is — it steps at each position close rather
  than marking to market every bar.
- **`FETCHING_DATA` says "downloading market data"**, not "running". The engine went out of its way
  to make that a separate state.
- **Kill is not stop.** Two different buttons, two different colors, and the kill dialog says in
  plain words that exits stop too and the position becomes yours to close at the exchange.

---

# 9. Build sequence — six phases

Phased rather than a flat list of steps, and run the way `packages/engine_server/CLAUDE.md`
already asks work to be run:

- **A phase's gate is a gate.** The acceptance checks below must pass before the next phase's
  first task starts. A phase whose gate cannot be made green is a design problem to surface, not
  a step to skip.
- **Ask before starting a phase.** Beginning one is your call. Steps *inside* an already-started
  phase follow the usual one-step-per-session rhythm.
- **Each phase ends somewhere demonstrable** — something to click, curl or read, not "the module
  is written".

## Phase map

| Phase | Owns | Blocks | Gate, in one line |
|---|---|---|---|
| **0** | Answering §10 | 1, 2 | Six questions decided. |
| **1** | `engine_server` (Python) | 4 | `curl` returns equity rows for a real job id. |
| **2** | `apps/server` plumbing + Prisma | 3 | The catalog reaches the browser through Hono. |
| **3** | Strategy authoring, end to end | 4 | A strategy is authored, versioned, and rejected with field-level errors. |
| **4** | Backtest, end to end | 5 | **The demo.** Author → run → read the result. |
| **5** | Simulation (paper), end to end | — | Promote, watch, stop, kill. |
| **6** | Polish and hardening | — | Every screen has a considered empty, loading and failed state. |

**Phases 1 and 2 are independent** — different languages, different files, no shared surface — so
they can run side by side. Everything from 3 onward is sequential, because each phase consumes
the data the previous one produces.

---

## Phase 0 — Decisions

**Goal.** Close §10 so Phases 1 and 2 are not built twice.

Only three of the six actually block work:

| Question | Blocks | Why it cannot wait |
|---|---|---|
| Q1 — spec validation: engine endpoint or Zod in Hono? | Phase 1 scope | Decides whether Phase 1 ships one route or two. |
| Q6 — do engine and `apps/server` share a host? | Phase 1 design | If they split, `NT_ARTIFACT_PATH` must move to object storage *before* the artifact route is written, not after. |
| Q2 — fold `apps/web` into the pnpm workspace? | Phase 2 | Decides whether request/response types are shared or hand-written. |

Q3 (which spec contract is authoritative) is a confirmation rather than a choice. Q4 and Q5 are
copy and defaults — they can be answered as late as Phase 4.

**Gate.** Q1, Q2 and Q6 answered in writing, here or in a reply.

---

## Phase 1 — Engine endpoints

**Goal.** Make the result series reachable over HTTP, so a backtest has something to draw.
**Depends on.** Phase 0 (Q1, Q6).
**Language.** Python. Nothing in TypeScript changes.

### Work

| # | Task | Files |
|---|---|---|
| 1.1 | `GET /v1/backtests/{job_id}/artifacts/{name}` — `name` validated against the closed set `{equity_curve, trades}`, `offset`/`limit` query params, rows read through `ArtifactStore.read_rows` | `src/engine/api/routes/backtests.py`, `src/engine/store/artifacts.py` |
| 1.2 | `POST /v1/specs/validate` — `StrategySpec.model_validate` + `validate_spec`, returning `{"ok": true}` or raising `SpecInvalid` **(only if Q1 chose the engine)** | new `src/engine/api/routes/specs.py`, registered in `api/app.py` |
| 1.3 | Tests for both, including the path-traversal case | `tests/api/` |
| 1.4 | Document both in the request reference and, if any code is new, the error-handling doc | `docs/explanations/request-reference.md`, `docs/explanations/error-handling.md` |

### Notes that matter here

- **`name` is never joined into a path from the request.** A path parameter reaching `fsspec` is a
  file-read primitive. Match against the closed set and map to a known filename; reject everything
  else with `NOT_FOUND` before any I/O.
- **Paginate server-side.** Inlining a 50,000-row curve contradicts the design note at the top of
  `store/artifacts.py`, and that note is right.
- A job with no artifacts (the `_persist` failure path returns `{}`) is a `404`, not a `500`.
- This phase adds no error codes if it reuses `JOB_NOT_FOUND` and `NOT_FOUND`. If it does add one,
  remember codes are append-only.

### Gate

```bash
cd packages/engine_server
uv run pytest && uv run ruff check . && uv run mypy src

# against the job already in ./artifacts
curl -H "Authorization: Bearer $NT_INTERNAL_API_KEY" \
  'localhost:8000/v1/backtests/job_b04a86e539564975b0dc03f0fa732157/artifacts/equity_curve?limit=5'
# -> {"rows":[{"time":"...","equity":"...","drawdown":"..."}],"total":47}

# and the traversal case
curl -H "Authorization: Bearer $NT_INTERNAL_API_KEY" \
  'localhost:8000/v1/backtests/job_b04a86e539564975b0dc03f0fa732157/artifacts/../../../etc/passwd'
# -> 404, and nothing read
```

Determinism tests still green — this phase touches no output path, and that must stay true.

---

## Phase 2 — Server foundations

**Goal.** `apps/server` can talk to the engine, store quant data, and return an error a client can
branch on. No user-visible feature yet.
**Depends on.** Phase 0 (Q2). Independent of Phase 1.

### Work

| # | Task | Files |
|---|---|---|
| 2.1 | `ENGINE_URL`, `ENGINE_INTERNAL_API_KEY` in the env schema and `.env.example` (**empty in the example — that file is committed**) | `src/env.ts`, `.env.example` |
| 2.2 | `ApiError` gains `details?: unknown` | `src/lib/api-error.ts` |
| 2.3 | `onError` emits `code` and `details`, matching `ApiErrorSchema`'s existing promise | `src/middlewares/on-error.middleware.ts` |
| 2.4 | Rate-limit key off `c.get('user').id`, falling back to IP | `src/middlewares/rate-limit.middleware.ts` |
| 2.5 | The engine client: bearer, `x-request-id` pass-through, snake→camel on responses, error-envelope translation | new `src/lib/engine-client.ts` |
| 2.6 | Four Prisma models + `User` back-relations + migration | `packages/prisma/schema.prisma` |
| 2.7 | `GET /api/v1/catalog/instruments`, with a ~60s in-process cache | new `src/routes/catalog/`, mounted in `src/app.ts` |
| 2.8 | Unit tests for the client's error translation and casing | `tests/unit/engine-client.test.ts` |

### Gate

```bash
pnpm --filter @quant/prisma db:migrate     # clean on a fresh database
pnpm --filter @quant/api test              # vitest green
pnpm check-types                           # whole repo
pnpm --filter @quant/api db:seed           # still runs
```

Plus, from a signed-in browser: `GET /api/v1/catalog/instruments` returns the engine's real
instrument list. Stop the engine and the same call returns **our** envelope carrying a `code` —
not a raw stack, and not an HTML page.

### Deferred out of this phase

No strategy, backtest or simulation routes. The catalog route exists here purely to prove the
whole chain — Privy token → `requireAuth` → engine client → bearer → FastAPI — with one endpoint
that cannot fail for interesting reasons.

---

## Phase 3 — Strategy authoring

**Goal.** A user can write a strategy in the browser, save it, revise it, and be told precisely
what is wrong with it.
**Depends on.** Phase 2. (Phase 1's validate route, if Q1 chose it.)

### Work

**`apps/server`** — `src/routes/strategies/`

- `GET /strategies`, `POST /strategies`, `GET /strategies/:id`, `POST /strategies/:id/versions`,
  `POST /strategies/validate`.
- Ownership on every read and write, from Postgres — never from the request (§7).
- Canonical-JSON spec hashing, shared by create and version so two paths cannot disagree.

**`apps/web`**

- Sidebar app shell added to the existing `(protected)/layout.tsx`, keeping the Privy guard and
  `useWalletSync` exactly as they are.
- `/strategies` list, `/strategies/[id]` builder.
- `components/strategy/condition-node.tsx` — one recursive component for `all` / `any` / `not` /
  leaf — and `spec-preview.tsx`.
- `lib/api/strategies/` in the same two-file shape as `lib/api/user/`.

### Gate

Demonstrable, in the browser:

1. Author `close crossesAbove sma(200)` with a 2% stop and 1% risk sizing, save it.
2. Reopen, change the period to 50, save → **version 2**, with version 1 still readable.
3. Delete the stop loss and save → rejected inline on the `exit` field with `MISSING_STOP_LOSS`,
   with no page-level error toast.
4. Try to add a 6th nesting level → the "add group" control is disabled, not a server error.

---

## Phase 4 — Backtest

**Goal.** The demo. Author → run → read an honest result.
**Depends on.** Phases 1 and 3. This is the first phase that needs both.

### Work

**`apps/server`** — `src/routes/backtests/`

- `POST /backtests` — row first, then mint `requestId`, then submit, then store `jobId`.
  **`200` is a replay, not an error**; never retry a submit with a fresh `requestId`.
- `GET /backtests/:runId` — reads the engine while non-terminal, **persists summary/error on
  terminal**, returns the merged view.
- `GET /backtests`, `DELETE /backtests/:runId`.
- `GET /backtests/:runId/equity` (downsampled to ~1,000 points), `GET /backtests/:runId/trades`
  (paginated).

**`apps/web`**

- `/strategies/[id]/backtest` form — instrument and bar type from the catalog, window, balances,
  fees, slippage.
- `/backtests/[runId]` — status timeline while running, then summary tiles, equity chart,
  drawdown, trade table. `/backtests` list.
- The 2s poll that stops on a terminal status.

### The honesty requirements land here, not in Phase 6

`totalFees` and `totalSlippage` on the tiles, not in a drawer · `openPositions > 0` stated
explicitly, with ending equity including `unrealizedPnl` · the curve labelled **realized** ·
`FETCHING_DATA` rendered as "downloading market data". These are the product thesis (§8.4), so
they are acceptance criteria, not polish.

### Gate

1. From `/strategies`, run SOL/USDT 15m over 2024-01-01 → 2024-03-01 and watch the status move
   `QUEUED → FETCHING_DATA → RUNNING → SUCCEEDED`.
2. The result page shows the summary tiles, an equity curve and the trade table.
3. Submit the identical run again → the existing run is returned, and the engine shows **one**
   job, not two.
4. **D1 holds:** `redis-cli -n 0 FLUSHDB` on the engine's queue Redis, reload the run page — the
   summary still renders, from Postgres.
5. A deliberately bad window (`sma(200)` over a 50-bar window) is rejected at submit with
   `INDICATOR_PERIOD_TOO_LARGE` against the right field.

---

## Phase 5 — Simulation

**Goal.** Promote a backtested version to paper, watch it converge, and stop it two different
ways.
**Depends on.** Phase 4 — a simulation is promoted from a version that has been backtested.

### Work

**`apps/server`** — `src/routes/simulations/`

- `POST /simulations` mints `accountId` (D3) and `PUT`s the engine. `GET /simulations` reads
  **our** table and enriches per row with a keyed `GET /v1/live/{accountId}` — `GET /v1/live` is
  never proxied (§7).
- `GET /simulations/:id`, `DELETE /simulations/:id`, `POST|DELETE /simulations/:id/kill`.
- The one-line difference: `slippageBps` moves **inside** `fees` on the live contract.

**`apps/web`**

- `/simulations` and `/simulations/[id]`, a 5s poll that pauses when the tab is hidden.
- `state-badge.tsx` covering `STARTING`, `RECONCILING`, `RUNNING`, `STOPPED`, `FAILED`, `HALTED`,
  plus "converging" when `observed.revision !== desired.revision` and "not heartbeating" when the
  heartbeat is stale.
- Stop and kill as two visually different actions. The kill dialog says in plain words that exits
  stop too and the position becomes yours to close at the exchange.

### Gate

1. Promote a version → `observed.status` reaches `RUNNING` with
   `observed.revision === desired.revision`, and the UI says so.
2. Edit the strategy, re-promote → the revision changes and the UI shows it converging, then
   matching again.
3. Stop → `STOPPED`, and the copy does **not** claim the position was closed.
4. Kill → `GET /v1/live/{id}/kill` reports `ENGAGED`; release returns it to `RELEASED`.
5. `HALTED` renders as needing an operator, not as a retryable error.

---

## Phase 6 — Polish and hardening

**Goal.** Every screen behaves when there is no data, slow data, or broken data.
**Depends on.** Phase 5.

- Empty states on all seven screens, each naming the next action.
- Loading skeletons using the `Skeleton` already in the kit; no layout shift on resolve.
- A route-level error boundary. Error toasts surface the `x-request-id`, which already traces
  browser → Hono → FastAPI — that is what makes a user's screenshot debuggable.
- Keyboard and focus order through the recursive builder, which is where it is easiest to get
  wrong. Contrast checked in both themes (`next-themes` is already wired).
- Phone width does not break. Nothing more — quant work does not happen on a phone.
- A copy pass over every destructive action and every honesty requirement from §8.4.

### Gate

Every screen demonstrated in four states — empty, loading, populated, failed — and the builder
driven start to finish with the keyboard alone.

---

# 10. Open questions — your call

1. **Spec validation** (§5.3): a second Zod validator in `apps/server`, or a new
   `POST /v1/specs/validate` on the engine? I recommend the engine endpoint — one authoritative
   validator is the DSL's core promise.
2. **`apps/web` is not in the pnpm workspace.** `pnpm-workspace.yaml` lists `apps/server`,
   `packages/*`, `engine`, `schemas` — not `apps/web`, which carries its own lockfile. So the web
   app cannot import a shared types package today. Fold it into the workspace (then
   `@quant/contracts` can hold the request/response types both sides use), or keep it standalone
   and hand-write the types in `lib/api/`? For v1 either works; the workspace is the better
   long-run answer.
3. **Two strategy-spec contracts exist in this repo.** `schemas/strategy-spec.v1.json` (snake_case,
   SMA-crossover only) belongs to the top-level `engine/` track; `packages/engine_server`'s
   Pydantic DSL (camelCase, six indicators) is what the running service actually accepts. This plan
   targets **engine_server's**. Confirm that is right, and that `schemas/` is not meant to become
   the shared contract for the UI.
4. **Fee defaults.** Fees and slippage are mandatory with no defaults, on purpose. Should the form
   pre-fill Binance spot's public rates (maker 10 bps / taker 10 bps, slippage 5 bps) as an
   editable suggestion, or force the user to type them every time? Pre-filling is kinder; typing
   is more honest. I lean pre-filled **with the source named in the field's help text**.
5. **Starting balance.** Backtests take `startingBalances` freely; a simulation's balance is fixed
   at `10 000 USDT` in engine code and deliberately not tunable. Should the backtest form also
   default to `10000 USDT` so the two are comparable by default?
6. **Does the engine run on the same host as `apps/server`?** The artifact endpoint reads from the
   engine's local disk, which is correct either way — but if you plan to split them, `NT_ARTIFACT_PATH`
   should point at object storage before Phase 1, not after.

---

# Reading further

- `packages/engine_server/docs/explanations/request-reference.md` — every field of both request
  contracts. The frontend forms are a direct transcription of it.
- `packages/engine_server/docs/explanations/live-api.md` — the live/paper lifecycle.
- `packages/engine_server/docs/explanations/error-handling.md` — the error envelopes and codes.
- `packages/engine_server/CLAUDE.md` — the 16 rules the engine will not bend on.
- `docs/privy-auth-integration.md` — why the rewrite/cookie path is shaped the way it is.
- `docs/Architecture_Plan.md` §17 — where `web` and `api-control` sit in the eventual five-service
  topology. `apps/server` is `api-control`.
