# Architecture Research

**Domain:** Multi-tenant AI-first crypto quant platform on a forked NautilusTrader
**Researched:** 2026-09-05
**Confidence:** HIGH for every claim about what Nautilus provides (verified against the local checkout, file:line cited). MEDIUM for the recommended shape — it is a design proposal, not an observed system.

All paths below are relative to `/Users/criox4/Codes/Trade_Platform/Nautilus_Engine /nautilus_trader` (note the trailing space in the parent directory name) unless prefixed with `quant-platform/`.

---

## Executive answer

Nautilus is not a library the control plane calls. It is a **peer process that owns a different kind of truth**, and the seam between them is a message boundary, not a function call. Everything in this document follows from that.

Three sentences that decide the architecture:

1. **The engine never reads Postgres to make a trading decision.** It reads only its own `Cache`. The moment an execution decision depends on a database round-trip, backtest and live have different code paths and the core value is gone.
2. **The control plane never writes an order.** It writes *permission*, and permission travels into the engine as a signed message that a Nautilus component consumes.
3. **The human-in-the-loop pause is a Nautilus `ExecutionAlgorithm`, not a blocked call.** This is the single integration question in the project and it has a clean, already-supported answer — see Pattern 1.

---

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│  web  (Next.js)                                                          │
│  Strategy Studio · Approval Center · Portfolio · Timeline · Chat          │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ HTTPS
┌───────────────────────────────▼──────────────────────────────────────────┐
│  api-control  (Hono + Prisma)          OWNS AUTHORIZATION TRUTH          │
│  ┌────────────┐ ┌────────────┐ ┌──────────────┐ ┌────────────────────┐   │
│  │ auth /     │ │ strategy   │ │ mandate +    │ │ ledger-writer      │   │
│  │ tenants /  │ │ registry   │ │ approval     │ │ (stream consumer)  │   │
│  │ accounts   │ │ (versions) │ │ + risk gate  │ │ + recon leg 2      │   │
│  └────────────┘ └────────────┘ └──────────────┘ └────────────────────┘   │
│  ┌────────────┐ ┌────────────┐ ┌──────────────────────────────────────┐  │
│  │ audit      │ │ kill       │ │ credential vault (KMS-wrapped DEK)   │  │
│  │ (append)   │ │ switches   │ │ — issues, never decrypts             │  │
│  └────────────┘ └────────────┘ └──────────────────────────────────────┘  │
└──────┬──────────────────────────────────────────────────▲────────────────┘
       │ commands (signed)                                 │ events
       │ approvals · lifecycle · halt                      │ orders · fills
       │                                                   │ positions
┌──────▼───────────────────────────────────────────────────┴────────────────┐
│  Redis streams — one inbound + one outbound key PER TENANT NAMESPACE       │
│  nautilus:v1:tenant:{t}:account:{a}:runtime:{r}:trader-{T}:stream          │
└──────┬───────────────────────────────────────────────────▲────────────────┘
       │ external ingress                                   │ external egress
┌──────▼───────────────────────────────────────────────────┴────────────────┐
│  engine-host  (Rust fork + embedded Python)   OWNS EXECUTION TRUTH        │
│  TenantHost ─┬─ TenantContext(A) → LiveNode(A) ──┐                        │
│              ├─ TenantContext(B) → LiveNode(B)   │  one full kernel each  │
│              └─ TenantContext(…) → LiveNode(…)   │                        │
│  ┌───────────────────────────────────────────────▼──────────────────────┐ │
│  │ per-tenant LiveNode = NautilusKernel                                 │ │
│  │  DslStrategy → ApprovalGate(ExecAlgorithm) → RiskEngine → ExecEngine │ │
│  │                          ▲ parks orders          ▲ inner backstop    │ │
│  │  Cache · Portfolio · MessageBus · DataEngine · Binance adapter       │ │
│  │  (plaintext exchange credentials live ONLY here, in memory)          │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────┬────────────────────────────────────────┘
                                   │ REST + WS (trade-only keys)
                              ┌────▼─────┐
                              │ Binance  │
                              │  spot    │
                              └──────────┘

┌───────────────────────────────────────────────────────────────────────────┐
│  ai-research  (Python / FastAPI)   NO CREDENTIALS · NO ORDER AUTHORITY    │
│  NL→StrategySpec compiler · research committee · explanation layer        │
│  Reaches api-control over HTTP only. Cannot reach Redis streams or KMS.   │
└───────────────────────────────────────────────────────────────────────────┘

┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Postgres    │  │  Timescale   │  │  Redis       │  │  Object store│
│  ledger +    │  │  market data │  │  cache DB +  │  │  evidence,   │
│  authz truth │  │  (backtest)  │  │  streams     │  │  artifacts   │
└──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
```

### Component Responsibilities

| Component | Owns (authoritative) | Explicitly does not own | Verified against |
|---|---|---|---|
| **Nautilus `Cache` + `ExecutionEngine`** | Order lifecycle, `OrderStatus`, fills, venue order IDs, positions, balances | Mandates, approvals, users, entitlements | `crates/model/src/enums.rs:1351-1382`; `crates/system/src/kernel.rs:98-140` |
| **Nautilus `Portfolio`** | Live exposure, unrealized/realized PnL, account state | Cross-tenant aggregation, historical analytics | `crates/system/src/kernel.rs:315-320` |
| **Nautilus `RiskEngine`** | Inner backstop: `TradingState` (Active/Reducing/Halted), max notional per instrument, balance sufficiency, price/qty precision | Mandate expiry, tenant identity, human approval, strategy-version approval | `crates/risk/src/engine/mod.rs:435,456,1042,1075,1100,2023,2198,2265` |
| **Nautilus reconciliation** | Leg 1: Nautilus ↔ Binance. Startup mass status, continuous open-order/position checks, external-order detection, deterministic synthetic IDs so restart replays dedupe | Leg 2: Nautilus ↔ Postgres | `crates/execution/src/reconciliation/mod.rs:16-41` |
| **`DslStrategy`** (ours, Python) | Translating evaluator `Action`s into Nautilus orders; setting `client_order_id = intent_id` | Strategy semantics (that is the evaluator), any risk decision | `python/tests/strategies/ema_cross.py:190-206` shows the exact contract |
| **`ApprovalGate`** (ours, `ExecutionAlgorithm`) | Parking an authorized-but-unapproved order; intent-hash re-verification; approval TTL | Deciding *whether* to approve | `crates/trading/src/algorithm/mod.rs:119,167,802-872,1412` |
| **`DslEvaluator`** (ours, pure Python) | Strategy semantics. Zero Nautilus imports | Order construction, engine anything | Locked by PROJECT.md Key Decisions |
| **`api-control`** | Tenants, users, accounts, strategy versions + lifecycle state, `AgentMandate`, `TradeIntent` record, `RiskDecision`, `Approval`, audit, entitlements, kill-switch authority | Order state, fill facts, positions, balances | — |
| **`ledger-writer`** | Projecting engine events into Postgres; leg-2 reconciliation; discrepancy escalation | Emitting commands to the engine (that is `api-control`) | — |
| **`ai-research`** | Proposals, evidence, explanations | Credentials, order authority, permission changes | Architecture_Plan §2, unchanged |

---

## Q1 · Where the boundary sits, and who wins

### The two truths own disjoint fields

They can never conflict on the same value, which is what makes "who wins" answerable at all.

| Field | Authoritative source | Postgres role |
|---|---|---|
| `OrderStatus`, venue order ID, filled qty, avg px, fees | Nautilus `Cache` | mirror |
| Position qty, avg px, PnL, account balance | Nautilus `Portfolio` | mirror |
| Did a valid mandate exist at intent time | Postgres | authoritative |
| Was there an approval bound to this exact intent hash | Postgres | authoritative |
| Is this strategy version APPROVED for live | Postgres | authoritative |
| Who the tenant is, what they are entitled to | Postgres | authoritative |

### Data flow, direction and cadence

**Control plane → engine (commands, low volume, event-driven):** exactly three message families, all signed by `api-control`, all delivered on the tenant's inbound Redis stream.

1. `StrategyLifecycle` — load spec vN into tenant, start, stop, retire. Single digits per day.
2. `ApprovalDecision` — `{intent_id, intent_hash, APPROVE|REJECT, expires_at, signature}`. Single digits per hour in Copilot.
3. `ControlAction` — `SetTradingState(Halted|Reducing)`, `CancelAllOrders`, `Flatten`. Rare, and it is the kill switch.

**Engine → control plane (events, high volume, continuous):** the full msgbus egress of order/fill/position/account events, published to the tenant's outbound Redis stream (`crates/infrastructure/src/redis/msgbus.rs:450-466`), consumed by `ledger-writer`, appended to Postgres. Every order event. The ledger is a projection, never a decision input.

**What never flows:** the engine never issues a synchronous read against Postgres. Not for balances, not for mandates, not for approvals. If a decision needs control-plane data, that data must have already arrived as a command *before* the decision point. This is non-negotiable — it is the property that keeps backtest and live on one code path.

### Conflict resolution

Because the fields are disjoint, "conflict" always means one of three *classes*, each with a different action:

| Class | Meaning | Action |
|---|---|---|
| Ledger is missing an event Nautilus has | Egress stream gap or writer downtime | Replay from Redis stream by ID. Benign, self-healing. |
| Ledger has an order with no `Approval` row | Something submitted an order the control plane never authorized | **Security incident.** Platform-level halt, page a human. |
| Position quantity differs after full replay | Genuine divergence, or a leg-1 failure Nautilus already flagged | Account-level halt. Nautilus's own venue reconciliation is the tiebreaker, not Postgres. |

---

## Q2 · The outer gate: split, not relocated

Architecture_Plan §7 describes one "deterministic risk kernel" running ~20 checks. Roughly half of those checks **cannot be correctly evaluated in the TypeScript control plane**, because the control plane's view of balance and position is a lagged mirror. Evaluating them there produces double-rejections and phantom allows, and it silently reintroduces a second position-tracking system — exactly the thing PROJECT.md put in Out of Scope.

So split by what each side can actually see:

**Outer gate, in `api-control` (TypeScript, at intent time).** Everything that is authorization truth and needs Postgres:
- agent active; mandate active, unexpired, unrevoked
- strategy version is the APPROVED one
- symbol / market type / side / order type permitted by mandate
- account and exchange enabled; entitlements satisfied
- daily turnover, daily loss, drawdown limits (ledger-derived, and correctly so — these are policy windows, not live money)
- circuit-breaker state
- intent not already processed (idempotency by `intent_id`)

Output: a `RiskDecision` row bound to `intent_hash`, signed, short TTL. This is Architecture_Plan §7's `RiskDecision`, unchanged in shape.

**Enforcement of the outer gate, in the engine.** The `ApprovalGate` `ExecutionAlgorithm` refuses to release any order without a matching signed decision whose recomputed `intent_hash` equals the hash of the order it is holding. The gate is the enforcement point; the control plane is the decision point. Separating them means a bug in the TS gate cannot release an order and a bug in the gate cannot forge a mandate.

**Inner backstop, Nautilus `RiskEngine` (unchanged, stays enabled).** Everything that is money truth against the live `Cache`:
- available balance sufficiency (`check_cash_sell_balance`, `crates/risk/src/engine/mod.rs:2023`)
- max notional per order per instrument (`set_max_notional_per_order`, `:456`)
- price and quantity precision, min/max exchange limits (`check_order_price` `:1075`, `check_order_quantity` `:1100`)
- `TradingState` gating (`:2265-2355`)

Two independent gates in two components in two languages. PROJECT.md calls this a feature; the file layout above is what makes it actually independent rather than nominally so.

**Anti-pattern flagged:** do not port Architecture_Plan's balance/exposure/slippage checks into TypeScript. They belong to the engine and are already implemented there.

---

## Q3 · The Copilot approval loop — the concrete answer

### Why the naive framing is wrong

"Nautilus strategies submit orders synchronously, so a human pause blocks the engine" assumes `submit_order` sends the order. It does not. It **routes** the order and returns:

```rust
// crates/trading/src/strategy/mod.rs:207-211
if order.emulation_trigger().is_some() {
    send_emulator_command(TradingCommand::SubmitOrder(command));
} else if let Some(exec_algorithm_id) = order.exec_algorithm_id() {
    send_algo_command(command, exec_algorithm_id);
} else {
    send_risk_command(TradingCommand::SubmitOrder(command));
}
```

Three destinations. The middle one is the hook. The strategy returns immediately regardless; nothing awaits.

**Rejected alternative — `OrderEmulator`.** Semantically the closest (it has real `Emulated` → `Released` order statuses that Nautilus persists), but it hard-rejects any trigger that is not price-based:

```rust
// crates/execution/src/order_emulator/emulator.rs:568-575
if !matches!(emulation_trigger,
    Some(TriggerType::Default | TriggerType::BidAsk | TriggerType::LastPrice)) {
    log::error!("Cannot emulate order: `TriggerType` {emulation_trigger:?} not supported");
    ... cancel_order ...
}
```

There is no manual-release trigger. Using it would mean patching the emulator — more fork surface, in a component upstream changes often.

**Rejected alternative — a custom `ExecutionClient` that holds orders.** By the time an order reaches a client it is already `Submitted`, a venue-bound status with no venue order behind it. That poisons reconciliation, which is the one subsystem you most want untouched.

**Rejected alternative — the strategy holds the order object and waits for a callback.** The order never enters the `Cache`, is never persisted, and is lost on crash. A parked intent must be durable.

### The design: `ApprovalGate` as an `ExecutionAlgorithm`

One per tenant node, Python subclass of the pyo3-exposed `PyExecutionAlgorithm` (`crates/trading/src/python/mod.rs:50`). Registered as the sole `exec_algorithm_id` on every order a `DslStrategy` emits **in live mode only**.

```
 ┌─ engine event loop, single thread, never blocked ─────────────────────┐
 │                                                                       │
 │ 1. Bar arrives → DslStrategy.on_bar(bar)                              │
 │      evaluator(spec, bars) → Action                                   │
 │      order = MarketOrder(client_order_id = intent_id,                 │
 │                          exec_algorithm_id = "APPROVAL-GATE")         │
 │      self.submit_order(order)            ── returns immediately ──┐   │
 │                                                                   │   │
 │ 2. Nautilus: cache.add_order(); publish OrderInitialized;         │   │
 │    route SubmitOrder → ApprovalGate.execute → on_order(order)  ◄──┘   │
 │    (crates/trading/src/algorithm/mod.rs:135-141, 167)                 │
 │    (order is now DURABLE in the Cache at status Initialized;          │
 │     nothing is on the wire)                                           │
 │                                                                       │
 │ 3. ApprovalGate.on_order:                                             │
 │      pending[client_order_id] = order                                 │
 │      publish_signal("trade_intent", TradeIntent{...})  ─── egress ──► │
 │      clock.set_time_alert_ns(now + ttl)                               │
 │      return                              ── returns immediately ──    │
 │                                                                       │
 │ ... engine keeps processing bars, fills, everything ...               │
 │                                                                       │
 │ 6. ApprovalDecision arrives on inbound stream                         │
 │      → external ingress → republish onto tenant msgbus                │
 │        (crates/live/src/node/mod.rs:1760-1776, 1949)                  │
 │      → ApprovalGate handler:                                          │
 │          verify signature                                             │
 │          recompute intent_hash FROM THE HELD ORDER, compare           │
 │          match  → self.submit_order(order, …)                         │
 │                   → risk_engine_queue_execute                         │
 │                     (crates/trading/src/algorithm/mod.rs:866-869)     │
 │                   → RiskEngine → ExecEngine → Binance                 │
 │          mismatch or REJECT → cancel_order, publish IntentRejected    │
 │                                                                       │
 │ 7. Time alert fires with no decision → cancel_order, IntentExpired    │
 └───────────────────────────────────────────────────────────────────────┘
```

Steps 4–5 (mandate gate, human sees preview, human clicks approve) happen entirely in `api-control` and the web app, on their own clock. The engine has no idea they are happening.

**Why the engine is never stalled:** every engine-side step is a message handler that returns immediately. The "pause" is an entry in a dict plus a timer — structurally identical to how the `OrderEmulator` already parks orders, which is proof the pattern is native rather than grafted on.

**Verified primitives this depends on, all present:**

| Need | Nautilus provides | Cite |
|---|---|---|
| Intercept before the venue | `exec_algorithm_id` routing | `crates/trading/src/strategy/mod.rs:209` |
| Receive the parked order | `ExecutionAlgorithm::on_order` | `crates/trading/src/algorithm/mod.rs:167` |
| Durable parking | `cache.add_order` runs before routing | `crates/trading/src/strategy/mod.rs:179-189` |
| Release later | `ExecutionAlgorithm::submit_order` → `risk_engine_queue_execute` | `crates/trading/src/algorithm/mod.rs:802-872` |
| Approval TTL | `Clock::set_time_alert_ns`, `on_time_event` | `crates/common/src/clock.rs:149`; `algorithm/mod.rs:1412` |
| Inbound decision channel | external msgbus ingress → republish | `crates/live/src/node/mod.rs:1760-1776, 1949` |
| Outbound intent channel | `publish_signal` / `publish_data` → egress | `crates/common/src/actor/data_actor.rs:780, 768` |
| Python subclassing | `PyExecutionAlgorithm` | `crates/trading/src/python/mod.rs:50` |

**Correlation carrier — a one-line fork improvement.** `SubmitOrder::new` has a `correlation_id` parameter that is passed `None` at *both* construction sites (`crates/trading/src/strategy/mod.rs:205`, `crates/trading/src/algorithm/mod.rs:858`). Threading `intent_id` through it is cleaner than stuffing it into `params: Option<Params>`, and is a plausible upstream contribution rather than fork debt.

**What we must add that Nautilus will not do for us:** on restart, `ApprovalGate.on_start` must rebuild `pending` by scanning the `Cache` for `status == Initialized && exec_algorithm_id == APPROVAL-GATE` and re-arm the timers. Algo-internal state is not persisted. See Q9.

**Backtest and paper are unaffected.** The `ApprovalGate` is simply not registered, and `DslStrategy` sets `exec_algorithm_id = None`, sending orders straight to the `RiskEngine`. The evaluator and the strategy file are byte-identical in all three environments. Only wiring differs. This is what protects the core value.

---

## Q4 · Multi-tenancy: architectural assessment of `768cbf3664`

### Isolation model as built

Per-tenant **ownership** of everything, plus **cooperative thread-local rebinding** for legacy global APIs.

- `TenantContext` owns one whole `LiveNode` — therefore one kernel, cache, portfolio, all engines, message bus, and data/exec clients (`crates/live/src/tenant.rs:129-171`). Isolation of *state* is by construction and is genuinely strong.
- `NautilusKernel` gained a `message_bus` field so a bus can be reached without the thread-local (`crates/system/src/kernel.rs:+101, +651-657`). Good change; removes a whole class of ambiguity.
- `MessageBusScope` is an RAII guard that swaps the thread-local bus and restores the previous one on drop (`crates/common/src/msgbus/mod.rs:+207-247`). `RunnerScope` does the same for seven runner sender bindings (`crates/live/src/runner.rs:+194-227, +319-331`).
- `TenantId` is validated namespace-safe; `TenantNamespace{tenant, account, runtime_instance}` produces a collision-resistant Redis prefix with percent-encoding of components (`crates/common/src/tenant.rs:35-45, 137-171`). This part is careful and correct.
- `TenantEnvelope::validate_scope` rejects cross-tenant and cross-runtime routing (`crates/common/src/tenant.rs:196-210`).
- `TenantHost` holds a `BTreeMap` of tenants, bounded per-tenant command queues, and a round-robin `dispatch()` (`crates/live/src/tenant.rs:391-546`).

### Where the seams are

| Seam | Strength | Note |
|---|---|---|
| Per-tenant engine state (cache, portfolio, orders) | **Strong** — separate objects, no shared mutable state | by construction |
| Redis durable namespace | **Medium** — correct when configured, fails open when not | see D5 |
| Thread-local msgbus / runner rebinding | **Weak** — a discipline, not a boundary | see D1 |
| `TenantHandle` capability | **In-process only** — plain UUID4 in memory, unsigned, unpersisted | see D7 |
| Inbound external stream keys | **None** — caller-supplied config | see D6 |

### Defects found

**D1 — Scope guards are held across `.await`. This is the tenant leak.**
`LiveNode::start` (`crates/live/src/node/mod.rs:352-354`) and `run_with_mode` (`:986-988`) each enter both guards and then await extensively; `run_with_mode` holds them across the *entire event loop*. `NautilusKernel::start_async`, `connect_data_clients`, `connect_exec_clients`, `finalize_stop` do the same (`crates/system/src/kernel.rs:+783, +1089, +1101, +1114`).

On a single-threaded runtime — which the patch's own doc comment mandates, "`TenantHost` is intentionally single-threaded: the underlying engines use `Rc<RefCell<_>>`" (`crates/live/src/tenant.rs:19-20`) — if two tenants' futures are ever polled on the same thread, this happens:

```
tenant A enters scope (previous = none)     → bus = A
A awaits; executor polls B
tenant B enters scope (previous = A)        → bus = B
B awaits; executor polls A
A resumes  ────────────────────────────────► bus = B   ← A's strategy now
                                                          publishes to B's bus
```

Guards restore in **drop order**, which has no relationship to **interleave order**. Consequence: tenant A's `submit_order` reaches tenant B's `RiskEngine` and lands on B's Binance account. Both orders are individually valid, so nothing errors — it is a silent, catastrophic leak. PROJECT.md names exactly this as the project's riskiest artifact; this is the mechanism.

**D2 — `TenantHost` never drives tenant event loops. The multi-tenant runtime does not exist yet.**
`TenantHost::dispatch()` handles only `Start | Stop | Suspend | Resume | Destroy` (`crates/live/src/tenant.rs:340-353, 498-545`). It starts tenants via `TenantContext::start()` → `LiveNode::start()`, whose own doc says:

> "…does not consume the runner or drive channel receivers, so channel traffic arriving after startup is never serviced. This is a building block for tests and embedding, not a lifecycle: use `run` or `run_with_mode` to run a node." — `crates/live/src/node/mod.rs:344-347`

So the patch as committed yields N *started* tenants that process nothing. There is no per-tenant event pump. This is the largest missing piece and it is also precisely where D1 must be solved — because the obvious way to write the pump (drive N `run_with_mode` futures on one `LocalSet`) is the exact interleaving that triggers D1.

**Recommended shape for the missing pump:** do not interleave futures. Give the host an explicit, synchronous, per-tenant turn: drain a bounded batch from tenant A's runner channels *inside* `with_message_bus(A, …)` with no await, drop the scope, move to B. That makes the guard sound because it is never held across a suspension point, and it makes fairness explicit and testable. It also means the fork needs a `LiveNode::pump_once()` — a decomposition of `run_with_mode`'s select loop into a non-async single-turn step. That is real work and belongs in the roadmap as its own phase.

**D3 — Three of four `TenantLimits` are declared but never enforced.** Only `max_queue_depth` is read (`crates/live/src/tenant.rs:437`). `max_open_orders`, `max_strategies`, `max_events_per_second` are validated non-zero (`:76-88`) and consulted nowhere in the tree. Either wire them or delete them; a limit that looks enforced and is not is worse than an absent one.

**D4 — The tenant Redis key always embeds `runtime_instance_id` and ignores `use_instance_id`. This breaks crash recovery.**
Compare:

```rust
// crates/infrastructure/src/redis/cache.rs:1213  (legacy)
if config.use_instance_id { key.push(':'); write!(key, "{instance_id}") }   // opt-in

// crates/infrastructure/src/redis/cache.rs:1230  (tenant)
let mut key = namespace.key_prefix();   // ALWAYS includes runtime:{uuid4}
```

With a fresh `instance_id` per boot, the tenant cache key rotates on every restart. Nautilus can never reload its own state, and abandoned keys accumulate in Redis forever. **Fix: persist a stable `runtime_instance_id` per `(tenant, account)` in Postgres and pass it as the node's instance id.** This is the highest-value single fix in the entire recovery story.

**D5 — Redis tenancy is opt-in and fails open.** `tenant_id: Option<String>`, default `None`, falls back to the unnamespaced legacy key (`crates/infrastructure/src/redis/cache.rs:+142-145, 341-352`; `msgbus.rs:+99-102, 453-466`). A missing config field is a silent cross-tenant *merge*, not an error. In the fork these fields should be required, or the backing constructor should refuse to build without them.

**D6 — Inbound stream keys are not tenant-derived.** Only `publish_messages` was namespaced. `stream_messages` reads whatever `external_streams: Vec<String>` the config hands it (`crates/infrastructure/src/redis/msgbus.rs:646-666`), with nothing validating that a tenant's node is reading its own stream. Inbound is where **approvals** arrive. A misconfiguration here means tenant A's node acts on tenant B's approvals. This must be a construction-time assertion in the fork, not a deployment convention.

**D7 — `TenantHandle` is an in-process capability only.** Unsigned UUID4 in memory (`crates/live/src/tenant.rs:98-108`), no persistence, no cross-process meaning. Fine as an in-process guard; it cannot be an authorization token the TypeScript control plane holds. This is not a defect so much as a confirmation of the PROJECT.md decision: authorization must stay in the control plane.

### What rigorous verification looks like

The existing tests are unit tests of the happy path (`crates/common/src/tenant.rs:238-283`, `msgbus/api.rs:+1732-1766`, `live/runner.rs:+2083-2106`). They cannot catch D1, because none of them interleave.

| Test | Catches | Shape |
|---|---|---|
| **Concurrent two-tenant interleave** | D1 | `LocalSet`, two tenant nodes, forced yields at each await, assert every published message lands only on the originating bus. Should fail today. |
| **Adversarial order property test** | D1, D2 | N tenants, randomized interleaved submissions, assert every `OrderFilled` appears in exactly one cache and it is the originating one |
| **Namespace disjointness** | D5 | assert prefixes disjoint; assert `RedisCacheDatabase::new` errors when `tenant_id` is absent |
| **Ingress binding** | D6 | assert a node configured with another tenant's `external_streams` fails at construction |
| **Restart identity** | D4 | start, write state, restart with same `(tenant, account)`, assert the same Redis key and full state reload |
| **Limits enforcement** | D3 | exceed each limit, assert rejection — or delete the fields |
| **Rebase CI** | fork maintainability | weekly rebase onto upstream `develop`, tenancy suite must stay green. This is engine tripwire (1) in PROJECT.md; automate it so the tripwire fires early rather than at month six. |

**Defense in depth outside the fork** — cheap and worth doing regardless: `ledger-writer` asserts the `tenant_id` on every event against the stream key it arrived on, and halts the platform on mismatch. A leak inside the engine then becomes a loud alert instead of a silent misrouted order.

---

## Q5 · Process topology: five services become four plus a worker

| Architecture_Plan §17 | Becomes | Why |
|---|---|---|
| `web` | `web` — unchanged | |
| `api-control` | `api-control` — **grows**: absorbs the authorization half of `trading-core` (mandate/policy engine, risk decisions, kill-switch authority, reconciliation leg 2) | Authorization truth belongs where Postgres is |
| `ai-research` | `ai-research` — unchanged, still credential-free | |
| `trading-core` | **dissolved.** Runtime half → `engine-host`. Authorization half → `api-control` | Nautilus owns strategy runtime, portfolio, OMS, market resolution |
| `execution-worker` | **absorbed** into `engine-host` | Nautilus's ExecClient is the execution worker. A separate one would need its own order state — the second OMS PROJECT.md forbids |
| — | **`engine-host` (new)**: the Rust fork + embedded Python. TenantHost, N LiveNodes, DslStrategy, ApprovalGate, RiskEngine, ExecEngine, Cache, Portfolio, Binance adapter, credentials | |
| — | **`ledger-writer` (worker, not a deployable)**: consumes tenant egress streams → Postgres; runs leg-2 recon. Recommend running it inside `api-control` for a 2-person team — it is a loop, not a service | Fewer things to operate |

**The new process boundary Architecture_Plan did not have:** the TS↔engine seam is now a **message boundary over Redis streams**, where §10's sequence diagram assumed in-process calls between Risk Kernel, OMS, and worker. Every arrow crossing that seam is now asynchronous and must be designed for at-least-once delivery and idempotent consumption.

**Security consequence — Architecture_Plan §16's permission table must be rewritten.** That table asserts "Live strategy runner: can access keys = No" and isolates `execution-worker` separately. In this topology the runner and the execution worker are the same process, so `engine-host` both runs strategy code and holds plaintext Binance credentials. Compensating controls, all of which should be explicit roadmap items:

- `engine-host` exposes **no inbound HTTP**. Its only ingress is the Redis stream, and every command on it is signed by `api-control`.
- Private subnet; egress allowlisted to Binance endpoints and Redis only. No LLM dependency, no outbound internet.
- Strategy code in `engine-host` is a **restricted DSL evaluated by our evaluator**, never arbitrary user Python. This is the reason the DSL seam is a safety control, not just an ergonomics choice.
- KMS unwrap only at tenant-node construction; plaintext in memory, never logged, never persisted.

---

## Q6 · The DSL seam and where it lives

### Packaging

```
quant-platform/
├── apps/
│   ├── web/                       # Next.js  (exists, scaffold only)
│   └── server/                    # Hono — becomes api-control
│       ├── src/routes/            # + strategies, mandates, intents, approvals, accounts
│       ├── src/services/          # mandate gate, risk decision, approval, kill switch
│       ├── src/workers/           # ledger-writer, recon leg 2, outbox dispatcher
│       └── prisma/schema.prisma   # + the whole trading domain (today: 4 auth models)
│
├── packages/
│   ├── contracts/                 # ★ zod. SOURCE OF TRUTH for the wire format.
│   │   ├── strategy-spec.ts       #   StrategySpec + validator (shape & vocabulary)
│   │   ├── mandate.ts             #   AgentMandate
│   │   ├── intent.ts              #   TradeIntent + intent_hash definition
│   │   ├── risk-decision.ts       #   RiskDecision
│   │   ├── approval.ts            #   ApprovalDecision (+ signature scheme)
│   │   ├── events.ts              #   OrderEvent, FillEvent, PositionSnapshot
│   │   └── jsonschema/            #   emitted in CI — the cross-language artifact
│   └── ...
│
├── engine/                        # ★ NEW top-level Python package (uv)
│   ├── contracts/                 #   pydantic, GENERATED from packages/contracts/jsonschema
│   │                              #   CI asserts regeneration is a no-op
│   ├── dsl/
│   │   ├── spec.py                #   StrategySpec (pydantic)
│   │   ├── evaluator.py           #   ★ DslEvaluator — PURE. zero nautilus imports.
│   │   └── indicators.py          #   plain-float indicator math
│   ├── adapters/
│   │   ├── dsl_strategy.py        #   ★ the SOLE Strategy adapter. imports nautilus.
│   │   └── approval_gate.py       #   ★ the ExecutionAlgorithm. imports nautilus.
│   ├── host/                      #   tenant node construction, config, KMS unwrap,
│   │                              #   stream wiring. imports nautilus.
│   └── tests/
│       ├── test_evaluator.py      #   no engine, no fixtures, milliseconds
│       └── golden/                #   ★ spec + bar series + expected actions
│
├── services/ai-research/          # Python/FastAPI (today: packages/fastapi-server)
└── docs/  .planning/
```

Nautilus-importing files: **exactly three** (`dsl_strategy.py`, `approval_gate.py`, `host/`). Engine lock-in is measurable and enforceable by a lint rule: `grep -rl 'nautilus_trader' engine/dsl/` must be empty, in CI.

### The TS/Python split, resolved

The tension is real: the spec is authored and validated in TypeScript (it must produce UI errors), and the evaluator must be Python (it runs inside Nautilus). The rule that prevents a second implementation:

- **TypeScript validates shape and vocabulary.** Is this a well-formed spec? Are these known indicator names, known operators, known parameters? Are the value ranges legal? It never simulates.
- **Python implements behaviour.** Given a spec and bars, what actions fire? It never re-validates shape — it may assume a validated spec.

They meet at two artifacts and nowhere else: the generated JSON Schema (structure) and the **golden fixture set** (behaviour). Every fixture is `{spec, bars, expected_actions}`; the Python CI job runs the evaluator against them, the TS CI job asserts every fixture spec passes the validator. A behaviour disagreement is impossible because only one side implements behaviour; a vocabulary disagreement fails CI immediately.

**Where the Nautilus fork does *not* get code:** no strategy, no evaluator, no DSL, no product logic. The fork carries the tenancy patch and nothing else, or it will not rebase. `engine/` lives in `quant-platform` and depends on the fork as a built wheel.

---

## Q7 · Market data: per-tenant in v1, with the fanout seam recorded

**What the patch implies:** per-tenant subscriptions, unavoidably. Each `TenantContext` owns a whole `LiveNode` (`crates/live/src/tenant.rs:135`) → its own kernel → its own `DataEngine` → its own Binance data client and WebSocket connection. N tenants = N connections to the same public streams, N copies of the same bars in memory.

**Recommendation for v1: accept it. Do not build a shared feed.** Reasons, in order:
1. Two users. The cost is literally two connections.
2. A shared feed introduces a *second* delivery path for market data, and any difference between how a backtest bar and a live bar reach the evaluator is exactly the drift Quant-Phase says kills trust. Adding it before the spine is boring is the wrong risk.
3. It is free — the patch already gives it.

**The upgrade path, and it already has a seam.** A `market-data-fanout` process holds one Binance connection, normalizes, and publishes onto per-tenant Redis streams; each tenant node consumes via the same external ingress that carries approvals (`crates/live/src/node/mod.rs:1760-1776`) and configures no data client of its own. Note the dependency: **this makes D6 (unvalidated ingress stream keys) load-bearing for market data as well as approvals** — fix D6 before taking this path, or a config typo feeds tenant A the wrong prices.

**Tripwires to build it:** Binance connection-count or request-weight limits reached; or duplicated order-book memory becomes the binding constraint on tenants-per-host.

---

## Q8 · Reconciliation: two legs, not three

### Leg 1 — Nautilus ↔ Binance: already built, do not rebuild

`crates/execution/src/reconciliation/mod.rs:16-41` documents exactly what Architecture_Plan §13 specifies:

- startup mass status and continuous open-order and position checks
- partial-window fill reconstruction
- external (manually created) order detection and event synthesis — Architecture_Plan's "manual user actions must be treated as intentional overrides"
- position quantity and average-price tolerance checks
- **deterministic synthetic `trade_id` / `venue_order_id`, so restart replays dedupe**

Startup reconciliation gates the trader: `perform_startup_reconciliation()` runs before `kernel.start_trader()`, and failure aborts startup (`crates/live/src/node/mod.rs:455-470`). **Architecture_Plan §13 is therefore about 80% already implemented.** Treat it as a requirement to *verify*, not to build.

### Leg 2 — Nautilus ↔ Postgres: ours, and the only one we build

- **Who:** `ledger-writer` inside `api-control`.
- **Schedule:** continuous by construction (it consumes the egress stream), plus a periodic full comparison at 60s, plus on every engine reconnect, plus on demand.
- **How it reads Nautilus truth:** a `StateSnapshotRequest` command on the tenant's inbound stream; the engine replies with a cache-derived snapshot of orders, positions, and balances. **Not** by querying Binance again.
- **What it compares:** the snapshot against the ledger's projection.

### Leg 3 — Postgres ↔ Binance: downgraded to a daily audit. *This changes Architecture_Plan §13.*

Architecture_Plan implies a live three-way loop. Recommend against it:
- If Nautilus agrees with Binance (leg 1, continuous, already built) and Postgres agrees with Nautilus (leg 2), transitivity gives you leg 3 for free.
- A second credentialed caller doubles the rate-limit surface and the credential blast radius for no new information.
- The only thing it independently catches is a systematic bug in leg 1 — which a **daily out-of-band audit from a separate read-only key** catches just as well, at a fraction of the operational cost and outside the control loop.

### Escalation to kill switches

The mechanism already exists — `RiskEngine::set_trading_state` (`crates/risk/src/engine/mod.rs:435`) with `Halted` and `Reducing` (`:2265-2355`).

| Level | Trigger | Action |
|---|---|---|
| Strategy | consecutive losses, slippage outside tested range, live/backtest divergence, stale data | stop that `DslStrategy` in the tenant node |
| Account | leg-2 mismatch after replay, unresolved stale `Submitted` orders, daily loss/drawdown, repeated auth failure | signed `SetTradingState(Halted)` to that tenant → optional `Reducing` (exits only) |
| Platform | ledger unavailable, audit write failing, order with no authorization row, clock drift, credential incident | halt every tenant **and** `ApprovalGate` refuses all releases |

The platform level deliberately uses **both** mechanisms. The gate and the risk engine are different components in different languages; a bug in one does not defeat the other. Per Architecture_Plan, **flattening stays separately configurable** — automatic market exits can themselves lose serious money.

---

## Q9 · Crash recovery with open positions

### What Nautilus already guarantees (verified)

| Guarantee | Cite |
|---|---|
| Cache persisted to a Redis database and reloaded via `config.load_state()` | `crates/infrastructure/src/redis/cache.rs`; `crates/system/src/kernel.rs:+796` |
| Startup reconciliation against the venue **before** the trader starts; failure aborts startup | `crates/live/src/node/mod.rs:455-470` |
| Deterministic synthetic IDs so post-restart replay dedupes rather than double-counting | `crates/execution/src/reconciliation/mod.rs:38-39` |
| Event store with a replay mode | `crates/live/src/node/mod.rs:377-386` |
| Parked (unapproved) orders survive, because `submit_order` caches before routing | `crates/trading/src/strategy/mod.rs:179-189` |

That is a genuinely strong baseline and a large part of why the engine decision is right.

### What the control plane must add

1. **Stable `runtime_instance_id` per `(tenant, account)`, persisted in Postgres.** Without it, D4 means the tenant Redis key rotates every boot and *none of the above works* — the cache is never found. This is prerequisite #1 for every other recovery guarantee.
2. **`ApprovalGate` pending-map rebuild** in `on_start`: scan the Cache for `Initialized` orders carrying the gate's `exec_algorithm_id`, re-arm expiry timers, re-publish intents still inside TTL. Nautilus does not restore algo-internal state.
3. **Expire every pre-crash approval.** Approval TTL is seconds; a restart almost certainly exceeds it. Releasing on a decision a human made against a pre-crash market is a bug that looks like a feature. Re-request.
4. **A `RECOVERED_UNRECONCILED` ledger state, surfaced in the UI.** Do not render a position as confirmed until leg-2 reconciliation has run post-restart. Silent confidence is the failure mode PROJECT.md's success metric is written against.
5. **Control-plane veto on trader start.** If the ledger and the recovered cache disagree materially, `api-control` withholds the start command. The engine holds the facts; the control plane holds the veto.

---

## Data Flow

### Live Copilot order — end to end

```
bar (Binance WS)
  → DataEngine → tenant msgbus → DslStrategy.on_bar
  → DslEvaluator(spec, bars) → Action                       [pure, no engine]
  → order(client_order_id = intent_id, exec_algo = GATE)
  → Cache.add_order + OrderInitialized                      [DURABLE]
  → ApprovalGate.on_order → park + timer
  → publish_signal(TradeIntent) → egress → Redis stream
  → ledger-writer → Postgres(trade_intents)
  → api-control: mandate gate → RiskDecision(signed) → Postgres
  → web: exact executable preview bound to intent_hash
  → HUMAN APPROVES
  → api-control: Approval row → signed ApprovalDecision → inbound stream
  → node external ingress → republish on tenant msgbus
  → ApprovalGate: verify sig, recompute intent_hash from held order, compare
  → submit_order → risk_engine_queue_execute
  → RiskEngine: balance, notional, precision, TradingState  [inner backstop]
  → ExecutionEngine → BinanceExecClient → Binance
  → OrderSubmitted/Accepted/Filled → Cache + Portfolio      [EXECUTION TRUTH]
  → msgbus egress → Redis → ledger-writer → Postgres        [MIRROR]
  → web timeline
```

Note where the hash is recomputed: **from the order the gate is holding**, not from the message. That is what makes "changing any parameter invalidates the approval" (Architecture_Plan §8) actually enforceable rather than merely stated.

### Backtest — the same path, minus two components

```
historical bars → BacktestEngine → DslStrategy.on_bar
  → DslEvaluator(spec, bars) → Action        ← IDENTICAL FILE, IDENTICAL CALL
  → order(exec_algo = None)
  → RiskEngine → SimulatedExchange → fills
```

The evaluator, the strategy adapter, and the spec are the same bytes. The only differences are the data source (already Nautilus's own abstraction) and the absence of the `ApprovalGate`. **This diagram is the core value. Any proposed change that makes these two flows structurally different should be rejected on sight.**

### Key flows, summarized

1. **Intent out, approval in** — engine → stream → control plane → human → control plane → stream → engine. Asynchronous, at-least-once, idempotent by `intent_id`.
2. **Execution events out** — engine → stream → ledger. One direction only. The ledger never talks back about execution.
3. **Commands in** — control plane → stream → engine. Signed. Three families only (lifecycle, approval, control action).
4. **Market data in** — Binance → per-tenant DataEngine. No control-plane involvement.
5. **Credentials** — KMS → engine-host memory at node construction. Never to `api-control`, never to `ai-research`, never to disk, never to logs.

---

## Architectural Patterns

### Pattern 1: Park-and-release via `ExecutionAlgorithm`

**What:** model a human-in-the-loop pause as durable state in an engine component plus a timer, never as a blocked call.
**When:** any time an external decision must gate an order without stalling a single-threaded event loop.
**Trade-offs:** free (uses an existing routing slot, zero fork surface); costs one extra component to test and an explicit restart-rebuild step. Strictly better than every alternative examined (see Q3).

```python
class ApprovalGate(ExecutionAlgorithm):
    def on_order(self, order):                    # returns immediately
        self._pending[order.client_order_id] = order
        self.publish_signal("trade_intent", intent_json(order), self.clock.timestamp_ns())
        self.clock.set_time_alert_ns(f"expire:{order.client_order_id}",
                                     self.clock.timestamp_ns() + self._ttl_ns)

    def on_decision(self, decision):              # from external msgbus ingress
        order = self._pending.pop(decision.intent_id, None)
        if order is None: return
        if decision.approved and intent_hash(order) == decision.intent_hash:
            self.submit_order(order)              # → risk engine → venue
        else:
            self.cancel_order(order)

    def on_time_event(self, event):               # TTL, no decision arrived
        cid = parse(event.name)
        if (order := self._pending.pop(cid, None)):
            self.cancel_order(order)

    def on_start(self):                           # ← we must add this; Nautilus won't
        for order in self.cache.orders(status=OrderStatus.INITIALIZED):
            if order.exec_algorithm_id == self.id:
                self._pending[order.client_order_id] = order
                self._rearm_or_expire(order)
```

### Pattern 2: Disjoint-field dual truth

**What:** two stores, each authoritative over fields the other never writes. Reconciliation checks *completeness*, never *precedence*.
**When:** whenever an engine you do not own holds state your product must display.
**Trade-offs:** eliminates the "two systems disagree about positions" failure PROJECT.md forbids. Costs discipline — every new field must be assigned an owner at design time, and the temptation to "just cache the balance in Postgres and read it in the gate" must be refused every single time.

### Pattern 3: Pure evaluator, single adapter file

**What:** strategy semantics in a module with zero engine imports; one adapter translating engine callbacks into evaluator calls.
**When:** whenever engine lock-in is a stated risk and strategy logic must be unit-testable.
**Trade-offs:** costs one indirection; buys millisecond unit tests, a measurable lock-in surface (three files), and the ability to swap engines without rewriting strategy semantics. Enforce with a CI grep, not a convention.

### Pattern 4: Signed commands over a namespaced stream

**What:** every control-plane→engine message is signed and carries `tenant_id`; the consumer verifies both the signature and that the tenant matches the stream it arrived on.
**When:** any cross-process authorization boundary — and specifically here, because `TenantHandle` (D7) cannot cross a process boundary.
**Trade-offs:** costs key management; buys a boundary that holds even if the in-process tenancy isolation (D1) has a bug. Given D1, this is not optional.

---

## Scaling Considerations

The meaningful axis is **tenants and open orders per host**, not end users.

| Scale | Adjustments |
|---|---|
| 1–10 tenants (v1) | One `engine-host`. Per-tenant Binance connections. `ledger-writer` inside `api-control`. Postgres for everything except candles. Timescale for candles. |
| 10–100 tenants | Fix D3 (enforce `TenantLimits`) — it becomes load-bearing. Build `market-data-fanout` (requires D6 fixed first). Split `ledger-writer` into its own deployable. Shard tenants across hosts by tenant id. |
| 100+ tenants | Multiple `engine-host` processes with a placement service; tenant→host mapping in Postgres. Move analytics off Postgres to ClickHouse. Re-examine the single-threaded-per-host constraint, which is where the whole tenancy design's ceiling sits. |

**Bottlenecks, in the order they will actually bite:**
1. **Correctness of the tenancy patch (D1/D2).** Not a scale limit — a correctness limit that presents at N=2. Everything else is downstream.
2. **Rust rebuild times.** PROJECT.md lists this as engine tripwire (3). Measure it in the first week; a slow loop for two people is an existential product risk, not an annoyance.
3. **Binance connection/weight limits** → triggers `market-data-fanout`.
4. **Single-threaded per-host event loop** → triggers host sharding.
5. Postgres write volume from `ledger-writer`. Distant last; batch the appends and move on.

---

## Anti-Patterns

### AP1: Building a second OMS in TypeScript
**What people do:** implement Architecture_Plan §9's state machine (`DRAFT → … → UNKNOWN → RECONCILING`) in Prisma and treat it as authoritative.
**Why it's wrong:** Nautilus's `OrderStatus` (`crates/model/src/enums.rs:1351-1382`) is authoritative and already reconciled against the venue. Two state machines produce two answers to "am I long?", which is worse than either alone — PROJECT.md's Out of Scope says exactly this.
**Instead:** map Architecture_Plan's states across the boundary. `DRAFT / AWAITING_APPROVAL / AUTHORIZED / RISK_REJECTED / QUEUED` are **control-plane intent states** and belong in Postgres. `SUBMITTING / ACKNOWLEDGED / PARTIALLY_FILLED / FILLED / CANCELLING / CANCELLED / REJECTED` are Nautilus statuses and are mirrored read-only. `UNKNOWN` has **no Nautilus equivalent** — it becomes a *derived ledger state*: `OrderStatus == Submitted` for longer than a threshold. `RECONCILING` is Nautilus's continuous behaviour, not a state to store.

### AP2: Reading Postgres inside the engine to make a trading decision
**What people do:** have the risk gate or the strategy query the mandate table on each signal, because it feels safer to check freshly.
**Why it's wrong:** it makes live depend on a database round-trip that backtest cannot have. The two paths diverge, and the divergence is invisible until real money behaves differently from the test. This is the one failure PROJECT.md says means the product has failed regardless of what else works.
**Instead:** push permission into the engine ahead of the decision, as a signed message the `ApprovalGate` holds. The engine's answer is always a function of engine state.

### AP3: Putting balance and exposure checks in the TypeScript gate
**What people do:** implement all ~20 of Architecture_Plan §7's checks in `api-control` because §7 lists them together.
**Why it's wrong:** the control plane's balance is a lagged mirror. It will disagree with the engine, producing rejections the user cannot explain and allows the engine then denies. It also reconstructs position tracking in TypeScript — AP1 wearing a different hat.
**Instead:** split by visibility. Mandate and policy in TS; money facts in the Nautilus `RiskEngine`, which already implements them against the authoritative cache.

### AP4: Treating the tenancy patch as verified because its tests pass
**What people do:** see green unit tests in `tenant.rs`, `msgbus/api.rs`, `live/runner.rs` and move on.
**Why it's wrong:** those tests never interleave two tenants, and interleaving is the whole risk (D1). A guard that restores in drop order looks correct in every sequential test and is wrong in every concurrent one.
**Instead:** the concurrency and property tests in Q4, plus the out-of-band `tenant_id` assertion in `ledger-writer`.

### AP5: Putting strategy or product code in the Nautilus fork
**What people do:** add the DSL evaluator to `crates/` because it needs to run inside the engine.
**Why it's wrong:** it makes the fork unrebasable, which fires engine tripwire (1) and forces the whole engine decision back open — for the one reason PROJECT.md explicitly says is *not* a tripwire.
**Instead:** `engine/` in `quant-platform`, depending on the fork as a built wheel. The fork carries the tenancy patch and nothing else.

### AP6: Building the live three-way reconciliation loop
**What people do:** implement Architecture_Plan §13 literally, with `api-control` holding Binance credentials to check positions directly.
**Why it's wrong:** doubles the credential blast radius and the rate-limit surface to re-derive something transitivity already gives, and it puts exchange keys in the process that also terminates user HTTP.
**Instead:** leg 1 (already built) + leg 2 (ours) as the control loop; leg 3 as a daily out-of-band audit from a separate read-only key.

---

## Integration Points

### External Services

| Service | Integration | Gotchas |
|---|---|---|
| Binance spot | Nautilus adapter, `crates/adapters/binance/src/spot/`. Trade-only keys, withdrawals disabled, IP allowlist | Only `engine-host` connects. `client_order_id` is ours (`python/tests/strategies/ema_cross.py:194`) — set it to `intent_id` and idempotency is free |
| Redis | Cache DB + inbound/outbound streams per tenant | D4 (unstable key) and D5 (fails open) must be fixed before it can be trusted for recovery or isolation |
| KMS | Per-account DEK unwrap at node construction | `ai-research` must have no network path to it. Enforce at the network layer, not in code |
| LLM providers | `ai-research` only, via a gateway | No path to Redis streams, KMS, or `engine-host` |

### Internal Boundaries

| Boundary | Communication | Notes |
|---|---|---|
| `web` ↔ `api-control` | HTTPS, OpenAPI-typed | scaffold exists |
| `api-control` → `engine-host` | Signed commands on per-tenant inbound Redis stream | Transactional outbox in Postgres (Architecture_Plan §18 — still correct, but for *commands*, not order submission) |
| `engine-host` → `api-control` | msgbus egress → per-tenant outbound stream → `ledger-writer` | At-least-once. Consumer idempotent by event id. Verify `tenant_id` against stream key |
| `DslStrategy` ↔ `DslEvaluator` | direct call, in-process | the seam. one direction, no engine types cross it |
| `DslStrategy` → `ApprovalGate` | Nautilus `SubmitOrder` routing via `exec_algorithm_id` | `crates/trading/src/strategy/mod.rs:209` |
| `ApprovalGate` → `RiskEngine` | `risk_engine_queue_execute` endpoint | `crates/trading/src/algorithm/mod.rs:866` — the queued endpoint is re-entrancy safe by design (`crates/risk/src/engine/mod.rs:160-170`) |
| `api-control` ↔ `ai-research` | HTTPS, sanitized snapshots only | no credentials, no order authority |

---

## Suggested Build Order

Dependencies are explicit. The deterministic spine (0–9) never depends on the AI planes (11).

| # | Component | Depends on | Exit gate |
|---|---|---|---|
| **0** | **Fork verification & repair.** Concurrency test proving D1; build `LiveNode::pump_once` + a real `TenantHost` event pump (D2); stable `runtime_instance_id` (D4); required tenant config (D5); ingress binding assertion (D6); enforce-or-delete `TenantLimits` (D3) | — | Two-tenant adversarial suite green, running on every rebase onto upstream `develop` |
| **1** | **Contracts freeze.** The six from PROJECT.md as zod + generated pydantic, plus `intent_hash` and the approval signature scheme | — | Generation is a CI no-op; golden fixtures exist |
| **2** | **Data layer.** Binance spot ingestion, point-in-time, survivorship-free, quality monitors | — | Gap/outlier/restatement monitors firing on real history |
| **3** | **DSL seam.** `StrategySpec` + `DslEvaluator` + golden fixtures. Pure Python | 1 | `grep -rl nautilus_trader engine/dsl/` empty; evaluator tests run without an engine |
| **4** | **Backtest path.** `DslStrategy` adapter + Nautilus BacktestEngine over layer-2 data | 2, 3 | **Reproduce a published backtest within tolerance.** Quant-Phase's acceptance test and engine tripwire (4) |
| **5** | **Control-plane spine.** Trading domain in Prisma, strategy registry state machine, encrypted credential storage, audit store | 1 | Registry enforces DRAFT→…→RETIRED; audit append-only |
| **6** | **Engine-host + stream boundary.** One tenant, no approval gate. Egress→ledger, inbound commands, paper trading on Binance testnet | 0, 4, 5 | Ledger matches engine state for a multi-day paper run |
| **7** | **Approval gate.** `ApprovalGate` algo, TS mandate gate, approval UI, `intent_hash` binding, TTL, restart rebuild | 6 | Every testnet order requires approval; a tampered preview fails the hash check |
| **8** | **Reconciliation leg 2 + kill switches.** Discrepancy detector, `TradingState` halt path, three breaker levels | 6 | Injected drift triggers a halt within one cycle |
| **9** | **Live Copilot, real money, small size** | 7, 8, and Q9's five recovery additions | Sustained live running with zero silent failures — PROJECT.md's success metric |
| **10** | **Validation suite.** Walk-forward, enforced OOS, parameter surfaces, Monte Carlo, deflated Sharpe | 4 | Runs in parallel with 6–9. Does not block live |
| **11** | **AI planes.** NL→spec compiler, research committee, explanation layer | 1, 3, 5 | Runs in parallel with 6–10. **Nothing in 6–9 may depend on this** |
| **12** | **Post-deployment monitoring.** Divergence, slippage attribution, decay, cross-strategy correlation | 9, 4 | The retention play; also the thing that proves 4 was honest |

**Parallelism for two people.** 0 and 2 have no dependency on each other and are the two longest-lead items — start both immediately. 1 is small and blocks 3, 5, and 11, so it goes first in whichever stream picks it up. Whoever is not on 0 can carry 1→3→4 all the way to the backtest reproduction gate without ever touching the fork.

**Phases likely to need their own deeper research:** 0 (the event-pump redesign is genuine engine work), 7 (approval-gate restart semantics and hash canonicalization), 8 (discrepancy taxonomy), 2 (survivorship-free Binance symbol history is harder than it sounds).

---

## Where Architecture_Plan.md Must Change

| § | Original | Supersedes to | Severity |
|---|---|---|---|
| §1 diagram | `SAFETY` plane contains OMS, portfolio, market resolver in TypeScript | Those move into `engine-host`. `SAFETY` retains policy/mandate, kill switches, outbox | **Structural** |
| §7 risk kernel | One kernel, ~20 checks, one place | Split: mandate/policy in TS at intent time; money facts in Nautilus `RiskEngine`. Enforcement of the TS decision happens in `ApprovalGate` | **Structural** |
| §9 OMS | Build an OMS with a 13-state machine | Nautilus's `OrderStatus` is the machine. Architecture_Plan's pre-submission states become control-plane intent states; `UNKNOWN` becomes a *derived* ledger state over a stale `Submitted`; `RECONCILING` is behaviour, not a state | **Structural** |
| §9 outbox | Outbox carries the order-execution command | Outbox carries control-plane→engine *commands*. Order submission is engine-internal and never crosses the outbox | **Structural** |
| §10 sequence | Runner → Risk → Approval → OMS → Worker, in-process | Strategy → `ApprovalGate` (park) → [async: TS gate, human] → gate release → `RiskEngine` → ExecClient. The Risk↔Approval hop is now a stream round-trip | **Structural** |
| §11 CCXT | Whole section: connection manager, capability registry, adapters, WS+REST | **Delete.** Nautilus Binance adapter | **Delete** |
| §12 idempotency | Build ID chain and search-before-resubmit | `client_order_id = intent_id` set by `DslStrategy`; search-before-resubmit is Nautilus reconciliation, already implemented | **Already built** |
| §13 reconciliation | Three-way live loop, build it all | Leg 1 already built — verify, don't build. Leg 2 is ours. Leg 3 downgraded to a daily out-of-band audit | **Mostly already built** |
| §14 kill switches | Build breakers | Mechanism exists (`set_trading_state`, `TradingState::Reducing`). Build the *triggers* and the escalation path | **Partially built** |
| §16 permissions table | "Live strategy runner: can access keys = No"; `execution-worker` isolated separately | **False in this topology** — runner and worker are one process. Rewrite the table; add the compensating controls in Q5 | **Security-relevant** |
| §17 five services | web, api-control, ai-research, trading-core, execution-worker | Four + a worker: web, api-control (grown), ai-research, engine-host (new); `ledger-writer` inside api-control | **Structural** |
| §17 repo structure | `packages/strategy-runtime`, `oms-models`, `exchange-adapters` | Delete all three. Add `engine/` (Python) and keep `packages/contracts` as the cross-language source of truth | **Structural** |
| §20 Phase 1 | "paper trading" as part of the intelligence-and-simulation phase | Paper now requires `engine-host` and the full stream boundary — materially heavier than assumed. It is build step 6, not a Phase-1 afterthought | **Sequencing** |
| §20 Phase 3 | Bounded Autopilot | Out of scope for v1 per PROJECT.md | **Scope** |

---

## Sources

**Primary — local checkout of `criox4/nautilus_trader`, branch `multi-tenant-nautilus-runtime`, HEAD `be9eaff8a7`, tenancy commit `768cbf3664` (1,372 lines / 18 files).** Every claim about engine behaviour above cites a file and line from this checkout. Confidence: HIGH.

Files read in full or in relevant part:
- `crates/common/src/tenant.rs` · `crates/live/src/tenant.rs` · full diff of `768cbf3664` across `msgbus/`, `runner.rs`, `live/runner.rs`, `node/mod.rs`, `kernel.rs`, `infrastructure/src/redis/`
- `crates/trading/src/strategy/mod.rs` · `crates/trading/src/algorithm/mod.rs` · `crates/trading/src/python/mod.rs`
- `crates/risk/src/engine/mod.rs` · `crates/execution/src/order_emulator/emulator.rs` · `crates/execution/src/reconciliation/mod.rs`
- `crates/model/src/enums.rs` · `crates/common/src/clock.rs` · `crates/common/src/actor/data_actor.rs` · `crates/common/src/msgbus/switchboard.rs`
- `crates/live/src/node/mod.rs` · `crates/system/src/kernel.rs` · `python/tests/strategies/ema_cross.py`

**Project documents:** `quant-platform/.planning/PROJECT.md` (Key Decisions treated as locked and not contradicted anywhere above) · `quant-platform/docs/Architecture_Plan.md` §§1–20 · `quant-platform/docs/Quant-Phase.md`

**Control-plane scaffold inspected:** `quant-platform/` — Turborepo + pnpm, `apps/server` (Hono + Prisma, one `user` route group), `apps/web` (Next.js, layout + page only), `packages/fastapi-server`. Confirms PROJECT.md's assessment: auth, a typed router, and a Prisma connection. No trading domain exists yet.

**No external sources were needed.** Every question could be answered from the checkout, which is the stronger answer.

---
*Architecture research for: multi-tenant AI-first crypto quant platform on a forked NautilusTrader*
*Researched: 2026-09-05*
