# Trade Platform

## What This Is

An AI-first crypto quant platform. A user describes a strategy in natural language; a
multi-agent research layer produces evidence-backed analysis, a compiler turns the intent
into a validated deterministic strategy spec, and that exact spec runs unchanged through
backtest, paper trading, and live execution on NautilusTrader. Live orders on Binance spot
require per-trade human approval (Copilot mode) and pass a deterministic risk gate that the
LLM cannot influence.

Built by a two-person team. First users are the builders, trading their own money.

## Core Value

**Backtest and live run the same engine, and the AI never touches credentials or order
submission.** If the simulator and the live path ever diverge, or if an LLM can reach
`createOrder()`, the product has failed regardless of what else works.

## Business Context

- **Customer**: Retail and semi-professional crypto traders who want AI research and
  strategy authoring without handing an LLM their exchange keys. Initially: the two builders.
- **Revenue model**: Not yet defined — no billing in v1.
- **Success metric**: v1 is proven when both builders run Copilot trades with real capital on
  Binance spot for a sustained period with zero silent failures (no unexplained position
  drift, no unresolved `UNKNOWN` orders, no tenant isolation leak).
- **Strategy notes**: `Architecture_Plan.md` (system architecture), `Quant-Phase.md`
  (platform design principles and build-order discipline), both in `docs/`.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

(None yet — ship to validate)

### Active

**Foundation**

- [ ] Stand up a clean NautilusTrader v2 node (pinned commit) with the tenancy patch shelved —
      one `LiveNode` process per tenant, Redis isolation provable by process boundary
- [ ] Establish the engine-agnostic DSL seam: `StrategySpec` + `DslEvaluator` (pure, zero
      Nautilus imports) + `DslStrategy` (sole adapter file)
- [ ] Freeze the six core contracts: `StrategySpec`, `AgentMandate`, `TradeIntent`,
      `RiskDecision`, OMS state machine boundary, reconciliation rules
- [ ] `ApprovalGate` as an `ExecutionAlgorithm` — the Copilot human-in-the-loop pause, using
      the `exec_algorithm_id` routing branch so backtest and live run identical strategy bytes
- [ ] Trials table (`strategy_lineage_id`, `params_hash`, `objective`, `ran_at`, `was_oos`)
      recorded from the very first backtest — cannot be reconstructed retroactively
- [ ] Daily `exchangeInfo` snapshot from day one — the survivorship history, not backfillable
- [ ] Durable `clientOrderId` write-ahead to Postgres before any HTTP submission, with a fresh
      ID per attempt and recorded lineage (Binance reuses IDs once an order leaves the book)

**Data and simulation**

- [ ] Binance spot market data ingestion with point-in-time correctness and
      survivorship-free symbol history
- [ ] Data quality monitors: gap detection, outlier flagging, exchange candle restatements
- [ ] Reproduce a published backtest within tolerance — the acceptance test for the
      foundation, before anything is built on top

**Strategy expression and validation**

- [ ] Restricted JSON strategy DSL with a validator that rejects unsupported or ambiguous rules
- [ ] Immutable versioned strategy registry (DRAFT → VALIDATED → BACKTESTED → PAPER_RUNNING
      → PAPER_PASSED → APPROVED → LIVE → PAUSED → RETIRED)
- [ ] Enforced in-sample / out-of-sample split where OOS is genuinely untouched during optimization
- [ ] Walk-forward analysis, parameter sensitivity surfaces, Monte Carlo on trade ordering
- [ ] Overfitting evidence surfaced to the user — every optimization attempt counts as a trial

**Control plane**

- [ ] Tenant-aware auth, users, and exchange account metadata (extends the better-auth scaffold)
- [ ] Encrypted exchange credential storage — per-account DEK wrapped by KMS, plaintext only
      in the execution path, never persisted or logged
- [ ] `AgentMandate` model with bounded scope, expiry, and revocation
- [ ] Deterministic risk gate evaluated before the engine, on every intent, mandate-aware
- [ ] Copilot approval flow — exact executable preview bound to an intent hash, short expiry
- [ ] Approval notification channels: Telegram bot and web push, both carrying the exact trade
      preview and approve/reject actions — without these the v1 success metric is unreachable
- [ ] Postgres ledger mirroring execution truth for UI, timeline, and audit
- [ ] Append-only audit store covering every fund-affecting action
- [ ] Circuit breakers and kill switches at strategy, account, and platform level

**Execution**

- [ ] Binance spot live execution through Nautilus with idempotent submission
- [ ] Continuous reconciliation across Nautilus, Postgres, and Binance with drift alerts
- [ ] Crash recovery with open positions
- [ ] Ambiguous-submission handling — `UNKNOWN` state, no blind retry, search before resubmit

**AI planes**

- [ ] Natural-language → `StrategySpec` compiler producing a validated spec
- [ ] TradingAgents research committee producing evidence-backed `SignalCandidate` artifacts
      with provenance and information-cutoff tracking
- [ ] Explanation layer — why a strategy fired, why a backtest looks as it does, where it is
      likely overfit
- [ ] Sanitized portfolio query tool for the AI plane (no credentials, no order authority)
- [ ] Open AI chat surface over markets, portfolio, strategies, and executions — sequenced
      after the evidence and provenance layer so it answers from real data

**Post-deployment monitoring**

- [ ] Live-vs-backtest divergence tracking with overlaid equity curves
- [ ] Slippage attribution — expected vs actual fill, per trade and aggregated
- [ ] Strategy decay detection — rolling Sharpe, alerts outside the backtest confidence band
- [ ] Cross-strategy correlation, so five variants of one bet are visible as one bet

### Out of Scope

- **Writing our own trading engine** — Nautilus supplies execution truth. Reconsider only on
  the recorded tripwires (see Key Decisions), never for DSL-fit reasons.
- **A second TypeScript OMS** — Nautilus already owns the order state machine; duplicating it
  produces two systems that disagree about positions, which is worse than either alone.
- **Second exchange, margin, perpetuals, leverage** — Architecture_Plan Phase 4. Each venue is
  a month of edge cases; earn the second one.
- **Custody or wallets** — existential security risk and a licensing question. Connect to
  user-owned accounts with trade-only, withdrawal-disabled keys.
- **Marketplace, copy trading, social feed, leaderboards** — needs supply and trust, may look
  like offering securities, and optimizes for luck-looks-like-skill.
- **Mobile app** — quant work does not happen on a phone. Approval *notifications* are in
  scope via Telegram and web push; a native app is not.
- **Multi-tenant density inside one runtime** — deferred, not abandoned. v1 has two tenants;
  process-per-tenant is provably isolated and costs nothing. Revisit when paying tenants make
  density a real constraint, and decide it then between upstreaming the seams or an orchestrator.
- **Three-way live reconciliation** — Nautilus↔Postgres is the enforced leg; a third
  credentialed caller against Binance doubles blast radius for information transitivity
  already provides. Binance is audited out-of-band, daily.
- **PineScript / LEAN strategy importer** — solves an empty-library problem that does not
  exist with two users. Revisit if a strategy-supply problem appears.
- **Our own trading model** — frontier models plus good tooling beats a small in-house model.
- **Autopilot mode** — Architecture_Plan Phase 3. v1 requires per-trade human approval.
- **Billing and entitlements** — no paying customers in v1.
- **Kafka** — unnecessary at this throughput. Postgres transactional outbox plus workers.
- **BullMQ** — Architecture_Plan §18's "outbox + BullMQ" is self-defeating: a Redis enqueue
  outside the Postgres transaction is the exact dual write an outbox exists to prevent. Use
  `pg-boss` so the enqueue is in the same transaction.
- **Cross-strategy correlation (for now)** — produces no signal below roughly 3 concurrent
  live strategies. Build it when that threshold is crossed.
- **Temporal** — revisit for long-running workflows once the spine is boring.

## Context

**Existing assets**

- `criox4/nautilus_trader`, branch `multi-tenant-nautilus-runtime` — a fork of
  `nautechsystems/nautilus_trader` carrying one substantive commit, `768cbf3664`
  "Add multi-tenant runtime isolation": 1,372 lines across 18 files introducing tenant
  identity (`crates/common/src/tenant.rs`, 300 lines), tenant lifecycle hosting
  (`crates/live/src/tenant.rs`, 671 lines), scoped message buses, runner bindings, bounded
  scheduling, and tenant-aware Redis namespaces. Touches `kernel.rs`, `msgbus`, and the Redis
  cache/msgbus layer. **Unverified.** This is the single riskiest artifact in the project —
  a tenant isolation leak in the msgbus or Redis namespace routes one user's orders into
  another user's engine.
- `criox4/quant-platform` (private) — the main development repo and the home of `.planning/`.
  Seeded from the `sutarrohit/Quant` template with no fork lineage. A scaffold, not a trading
  platform: root package named `template`. Turborepo +
  pnpm. `apps/server` is Hono 4 with `@hono/zod-openapi`, better-auth, Prisma 7 (pg adapter),
  pino, rate limiting, Swagger UI, vitest — one route group (`user`).
  `apps/server/prisma/schema.prisma` is 73 lines and four models (`User`, `Session`,
  `Account`, `Verification`), all better-auth tables, no trading domain.
  `apps/web` is Next.js + shadcn with only `layout.tsx` and `page.tsx`.
  `packages/fastapi-server` is FastAPI + alembic + uv with `users.py` and `posts.py`
  boilerplate. Value delivered: auth, an OpenAPI-typed router, a Prisma connection. Nothing more.
  The Nautilus fork remains a separate repo at `../Nautilus_Engine/nautilus_trader`, kept
  independent so it can rebase cleanly onto upstream `develop`.

**Source documents**

- `docs/Architecture_Plan.md` (1,453 lines) — three-plane separation, the six contracts to freeze
  first, the trust chain, five deployable services, and a four-phase build sequence. Written
  assuming a TypeScript strategy runtime and a CCXT execution worker; this project replaces
  both with Nautilus (see Key Decisions).
- `docs/Quant-Phase.md` — platform design principles. Its central claim drives this project's core
  value: backtest and live must run the same code path, and that cannot be retrofitted. Also
  the source of the layered build order and the "reproduce a published backtest" acceptance test.

**Research findings** (`.planning/research/` — STACK, FEATURES, ARCHITECTURE, PITFALLS, SUMMARY)

Four parallel researchers, all verified against the local checkout. What changed the plan:

- The tenancy patch is defective, not merely unverified — three of four researchers converged
  on overlapping defects independently. This reversed the multi-tenancy decision (see Key
  Decisions). The branch is archived as a record of the seams, not as a foundation.
- Nautilus v2 supplies far more than Architecture_Plan assumed: ~80% of §13 reconciliation
  (`reconciliation/mod.rs:16-41` — startup mass status, continuous open-order and position
  checks, external-order detection, deterministic synthetic IDs for restart dedupe), an
  append-only hash-chained event store (`crates/event_store/`, 40k LoC) that likely subsumes
  the audit-store requirement, and a native answer to the Copilot pause.
- Scale of what is *not* worth rebuilding, measured in this checkout: Binance adapter 140,612
  LoC; execution engine 78,247; backtest 37,101; live runtime 35,376; portfolio 20,781.
- Binance historical data is free and survivorship-free at `data.binance.vision` — klines from
  2017-08 with checksums, delisted symbols (`SALTBTC`, `BCCBTC`, `MITHUSDT`) still present. No
  data vendor needed for v1. No bulk loader in-tree, so ingestion is real work.
- Binance SBE market data refuses to connect without Ed25519, making the "API secret" a
  multi-line PKCS#8 PEM — this changes the credential schema and KMS envelope design.
- The Binance adapter does not filter order types against `exchangeInfo`, so the DSL validator
  must.
- Storage: `ParquetDataCatalog` + DuckDB, not ClickHouse or TimescaleDB yet — anything the
  backtest engine cannot read natively is a second copy that can disagree with the simulator.
- Validation tooling does not exist off the shelf (`pypbo` unmaintained, `mlfinlab`
  license-encumbered, vectorbt PRO commercial). Roughly 300 lines on numpy/scipy; the
  load-bearing part is the trial counter, which lives in the strategy registry.
- Supply-chain hazard: `pip install tradingagents` resolves to v0.7.0 from `Mai0313`, a
  third-party fork carrying a higher version number than the official 0.4.0. Build the research
  committee directly on LangGraph.
- NL→strategy generation benchmarks at ~70–76% single-turn, 95–98% agentic with validator
  feedback, and failures are semantic rather than syntactic — making the DSL validator
  load-bearing for the AI plane, not only for safety.
- Local `target/` is 18 GB.

**Known divergences from Architecture_Plan**

Architecture_Plan specifies CCXT and a hand-built TypeScript OMS, strategy runtime, and
execution worker. Nautilus supplies those. Sections 9–13 should be read as requirements on the
*boundary and the ledger*, not as a build list. The control plane keeps authentication,
mandates, approvals, entitlements, audit, and the product ledger. Specifically:

- **§11 (CCXT integration) — delete.** Superseded entirely by the Nautilus Binance adapter.
- **§12 (idempotency) — incomplete, and the gap is catastrophic.** Binance enforces
  `newClientOrderId` uniqueness *only among open orders*; once an order is filled or cancelled
  the ID is reusable and Binance will accept a new order under it. §12's "search, then retry
  with the same ID" therefore double-fires if the search misses a just-filled order. Missing:
  write-ahead of the `clientOrderId` to Postgres before the HTTP call, a fresh ID per attempt
  with recorded lineage, a settle delay before concluding no order exists, and a hard rule that
  Copilot never auto-resubmits.
- **§13 (reconciliation) — ~80% already built by Nautilus.** Build the Nautilus↔Postgres leg only.
- **§16 (service permission table) — now false.** The strategy runner and execution worker are
  one process, which therefore holds plaintext credentials. The table must be redrawn against
  the real topology before it is used as a security argument.
- **§17 (five services) — becomes four plus a worker**, since Nautilus absorbs `trading-core`
  and `execution-worker`.
- **§18 (outbox + BullMQ) — contradicted.** See Out of Scope.

**Corrections to Quant-Phase**

- "Almost nobody does validation properly" is false — StrategyQuant X, BuildAlpha, and Minara
  all ship walk-forward, Monte Carlo, and OOS handling today.
- "Almost no platform shows live-vs-backtest divergence" is false — QuantConnect ships Live
  Reconciliation, running an OOS backtest in parallel with every live deployment.
- Slippage attribution, strategy decay detection, and cross-strategy correlation were not found
  shipped anywhere; those three claims survive.
- Market context: Composer, the best-funded NL-to-strategy builder, exited crypto on
  2026-01-31 and was acquired by SoFi in June 2026. Exchanges are commoditizing agent execution
  plumbing (Coinbase for Agents, OKX Agentic Wallet, Gemini Agentic Trading, Kraken, Binance),
  so no part of the value proposition should rest on "an AI can place a trade."
- The safety architecture is table stakes, not a differentiator — Minara already markets this
  exact trust chain. It must be built; it cannot be led with.

**Housekeeping**

`Trade_Platform/ /nautilus_trader` (directory literally named with a single space) is a
duplicate Nautilus checkout. Left in place; delete when convenient. The abandoned
`criox4/Quant` fork also still exists on GitHub — delete with
`gh auth refresh -h github.com -s delete_repo && gh repo delete criox4/Quant --yes`.

## Constraints

- **Engine**: NautilusTrader **v2** (`v2.0.0rc4`), stock, pinned commit — chosen because
  backtest and live share one code path, which is the core value and cannot be retrofitted.
- **Fork maintenance**: none. The tenancy branch is archived, not built on. Track upstream
  `develop` directly. If density is ever needed, prefer upstreaming the seams (`kernel.rs:101`,
  kernel owning its bus, is a genuine improvement) over re-forking.
- **Venue**: Binance spot only for v1. One venue, one asset class, get it boring first.
- **Stack**: Hono + Prisma + Next.js control plane (`criox4/quant-platform` monorepo); Rust/Python
  Nautilus engine; Python AI plane. Three languages, matching Architecture_Plan's service split.
- **Team**: 2 people. Quant-Phase's 2–3 person-year estimate covers its Layers 0–6 only;
  adding the control plane, compiler, research committee, explanation layer, chat surface, and
  a three-language split puts the real figure at **4–6 person-years — 2–3 calendar years for
  two people**. Sequencing must therefore let the deterministic spine ship independently of the
  AI planes, and the AI planes must not start until a live Copilot order has been reconciled.
- **Trading mode**: Copilot only in v1 — every live order requires explicit human approval
  bound to an exact intent hash. Autopilot is out of scope.
- **Credentials**: Trade-only API keys with withdrawals disabled; IP allowlisting where
  available; the AI plane can never reach KMS.
- **Money representation**: Decimal strings for prices, quantities, fees, and balances. Never
  floating point as the authoritative monetary value.
- **Data**: Point-in-time correct and survivorship-free, or every number downstream is garbage.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| NautilusTrader is the engine, not CCXT | Backtest and live share one code path — the property Quant-Phase calls the #1 trust killer when absent, and impossible to retrofit. Nautilus also supplies the order state machine, fill/fee models, portfolio accounting, instrument precision, Binance adapter, and crash recovery that Architecture_Plan assumed would be hand-built. | — Pending |
| Engine-agnostic DSL seam: `StrategySpec` + `DslEvaluator` stay pure with zero Nautilus imports; `DslStrategy` is the sole adapter | The DSL is a strategy-level concern, not an engine concern — Nautilus's contract is `on_bar(bar)` in, `submit_order(order)` out, and the example strategy computes its own indicators in plain floats. Owning the evaluator (not the engine) is what makes the DSL fit perfectly. A pure evaluator is also the only way to unit-test strategy logic without an engine, so the seam costs nothing extra and reduces engine lock-in to one file. | — Pending |
| Do not build our own simplified engine | The liftable "core logic" is the clean 20%; the other 80% is accumulated edge cases — partial fills, `UNKNOWN` submissions, precision, reconnects, PnL accounting — rediscovered one wrong number at a time with real money on it. Extraction is also a permanent divorce from upstream fixes and adapters, for a two-person team. A simplified engine only stays simple if it stays bar-close spot forever, which Phase 4 ambitions contradict. | — Pending |
| Revisit tripwires for the engine decision | Reconsider **only** if: (1) the tenancy patch cannot be kept safe across rebases onto `develop`; (2) Binance adapter gaps block Copilot and upstream rejects the fix; (3) Rust rebuild times make the two-person iteration loop unworkable; (4) a published backtest cannot be reproduced and the cause is the engine rather than our data. "The DSL doesn't fit" is explicitly **not** a tripwire. | — Pending |
| Nautilus owns execution truth; the control plane owns authorization truth | Both Nautilus and Architecture_Plan want an OMS. Building both yields two systems disagreeing about positions — worse than either alone. Nautilus owns order lifecycle, fills, and positions. The control plane owns mandates, approvals, entitlements, and audit, since Nautilus's risk engine is per-node config with no concept of a tenant mandate expiring. | — Pending |
| Postgres is the product ledger, not a competing source of truth | It mirrors Nautilus's execution state for UI, timeline, and audit. Reconciliation compares Nautilus ↔ Postgres ↔ Binance three ways. | — Pending |
| Nautilus's risk engine stays on as an inner backstop | The mandate-aware deterministic gate runs before the engine; Nautilus's own risk engine remains enabled beneath it. Two independent gates is a feature, not duplication. | — Pending |
| ~~Multi-tenancy inside one runtime~~ **SUPERSEDED 2026-09-05** | Original rationale: a Kubernetes deployment per customer does not scale for many small, idle accounts. Reversed on evidence — see the next row. | ⚠️ Reversed |
| Shelve the tenancy patch; run stock Nautilus v2, one `LiveNode` process per tenant | Research found commit `768cbf3664` defective, not merely unverified: thread-local `MessageBusScope` guards held across `.await` on a self-declared single-threaded host (`crates/live/src/tenant.rs:259-262`, `node/mod.rs`, `kernel.rs`, `runner.rs:194-226` — one affected sender is the order-submission channel); Redis tenancy failing open to the legacy untenanted key; `TenantNamespace::key_prefix()` (`common/src/tenant.rs:170-177`) embedding a fresh random `runtime_instance_id` per process so crash recovery loads nothing and the engine believes it is flat while holding a position; no PyO3 surface (`python/redis/cache.rs:335-336` hardcodes `tenant_id: None`); and `TenantHost` starting tenants via `LiveNode::start()`, whose own doc (`node/mod.rs:342-347`) says it "does not consume the runner or drive channel receivers" — so there is no multi-tenant event pump at all. Coverage: one test in the 671-line isolation host, asserting a zero queue depth is rejected. Meanwhile v1 has exactly two tenants. Shelving costs nothing, makes isolation provable by process boundary, and drops fork maintenance to zero. | — Pending |
| Python hosts the runtime | Follows from shelving the patch: with process-per-tenant there is no Rust supervisor to write, `crates/live/src/tenant.rs` becomes archived rather than load-bearing, and `DslEvaluator` stays pure Python inside a Nautilus `Strategy` as the DSL seam intends. | — Pending |
| Track upstream `develop` with no local patch | With the patch shelved there is nothing to rebase. Measured cost of *keeping* it: 141 upstream commits touched the patched paths in 90 days (~47/month), and `HEAD` (`be9eaff8a7`) is already a merge rather than a rebase, so "thin and rebasable" was untrue when written. | — Pending |
| Pin NautilusTrader v2 (`v2.0.0rc4`), not v1 | `version.json` confirms v2; `TradingNode` does not exist, it is `LiveNode.builder(...)`. v1 (`origin/develop_v1`) receives security backports only. Consequence: v1-era tutorials and most model training data are wrong for this checkout, and `MIGRATION_V2.md` is required reading. Pin an exact commit — v2 is still an RC. | — Pending |
| Copilot approval implemented as an `ApprovalGate` `ExecutionAlgorithm` | `Strategy::submit_order` routes three ways (`crates/trading/src/strategy/mod.rs:207-211`); the `exec_algorithm_id` branch parks the order without awaiting, and `cache.add_order` runs *before* routing so the order is durable first. TTL via `Clock::set_time_alert_ns`; release via the algorithm's own `submit_order`. In backtest the gate is simply not registered. Same strategy file, same bytes, backtest and live. Rejected `OrderEmulator` (hard-rejects non-price triggers, `order_emulator/emulator.rs:568-575`) and a holding `ExecutionClient` (would mark orders `Submitted` with no venue order, poisoning reconciliation). | — Pending |
| Risk gate splits across the boundary rather than relocating | Mandate, policy, and entitlement checks run in TypeScript at intent time and emit a signed `RiskDecision`; the `ApprovalGate` enforces it in-engine; Nautilus's `RiskEngine` remains the money backstop. Balance, exposure, and precision checks stay in Nautilus because they cannot be evaluated correctly in TS against a lagged mirror. Two genuinely independent gates. | — Pending |
| `UNKNOWN` is a derived ledger state, not an engine state | Nautilus's `OrderStatus` (`model/src/enums.rs:1351-1382`) has no `UNKNOWN`. The ledger derives it from `Submitted` persisting beyond a threshold. | — Pending |
| Approval notifications via Telegram bot **and** web push | The v1 success metric is sustained Copilot trading; nobody watches a browser tab for a month. Telegram is the reliable mobile path with no app to ship, web push covers desktop. Neither is a mobile app. | — Pending |
| Full open AI chat surface | Chosen over artifact-scoped chat and over Quant-Phase's "don't build it yet". Sequenced after the evidence and provenance layer so it answers from real data rather than model priors. | — Pending |
| Differentiation is trial accounting plus an enforced OOS lockbox | Research falsified the broader claim: rigorous validation is already shipped (StrategyQuant X Monte Carlo and walk-forward matrices, Minara, BuildAlpha) and live-vs-backtest divergence is shipped by QuantConnect Live Reconciliation. What nobody surfaces is deflated Sharpe, PBO, or honest trial counts — and only the party running the optimizations can count them. Requires the trials table from the first backtest. | — Pending |
| Global crypto with execution, AI-first | Chosen over the research-tool-without-execution wedge and over Indian equity/F&O. Accepts the larger regulatory surface; mitigated by connecting to user-owned accounts with trade-only keys and holding no custody. | — Pending |
| v1 ships through Copilot live trading, dogfooded with our own money | Architecture_Plan Phase 2. Real capital on the line is what surfaces the bugs that matter, and unwillingness to run it ourselves would itself be information. | — Pending |
| All three AI capabilities are the product, but sequenced behind the deterministic spine | Research committee, strategy authoring, and explanation together are the differentiator. Sequencing them after the spine means a slip in the research committee never blocks live trading. | — Pending |
| Binance as the single v1 venue | Deepest liquidity and the most mature Nautilus adapter. | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Business Context check — customer, revenue model, success metric still accurate?
4. Audit Out of Scope — reasons still valid?
5. Update Context with current state

---
*Last updated: 2026-09-05 after project research*
