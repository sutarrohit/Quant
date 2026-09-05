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
  (platform design principles and build-order discipline), both at repo root.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

(None yet — ship to validate)

### Active

**Foundation**

- [ ] Verify the multi-tenant runtime isolation patch in the Nautilus fork — prove tenant
      scoping holds in the message bus, kernel, and Redis namespaces under adversarial test
- [ ] Establish the engine-agnostic DSL seam: `StrategySpec` + `DslEvaluator` (pure, zero
      Nautilus imports) + `DslStrategy` (sole adapter file)
- [ ] Freeze the six core contracts: `StrategySpec`, `AgentMandate`, `TradeIntent`,
      `RiskDecision`, OMS state machine boundary, reconciliation rules
- [ ] Rebase the tenancy patch onto upstream `develop` and keep it rebasable

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
- **Mobile app** — quant work does not happen on a phone.
- **Our own trading model** — frontier models plus good tooling beats a small in-house model.
- **Autopilot mode** — Architecture_Plan Phase 3. v1 requires per-trade human approval.
- **Billing and entitlements** — no paying customers in v1.
- **Kafka** — unnecessary at this throughput. Postgres transactional outbox plus workers.
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
- `criox4/Quant` — forked from `sutarrohit/Quant`, cloned to `Trade_Platform/Quant`. A
  scaffold, not a trading platform: one commit, root package named `template`. Turborepo +
  pnpm. `apps/server` is Hono 4 with `@hono/zod-openapi`, better-auth, Prisma 7 (pg adapter),
  pino, rate limiting, Swagger UI, CDK deploy scripts, vitest — one route group (`user`).
  `apps/server/prisma/schema.prisma` is 73 lines and four models (`User`, `Session`,
  `Account`, `Verification`), all better-auth tables, no trading domain.
  `apps/web` is Next.js + shadcn with only `layout.tsx` and `page.tsx`.
  `packages/fastapi-server` is FastAPI + alembic + uv with `users.py` and `posts.py`
  boilerplate. Value delivered: auth, an OpenAPI-typed router, a Prisma connection. Nothing more.

**Source documents**

- `Architecture_Plan.md` (1,453 lines) — three-plane separation, the six contracts to freeze
  first, the trust chain, five deployable services, and a four-phase build sequence. Written
  assuming a TypeScript strategy runtime and a CCXT execution worker; this project replaces
  both with Nautilus (see Key Decisions).
- `Quant-Phase.md` — platform design principles. Its central claim drives this project's core
  value: backtest and live must run the same code path, and that cannot be retrofitted. Also
  the source of the layered build order and the "reproduce a published backtest" acceptance test.

**Known divergences from Architecture_Plan**

Architecture_Plan specifies CCXT and a hand-built TypeScript OMS, strategy runtime, and
execution worker. Nautilus supplies those. Architecture_Plan sections 9–13 (OMS state machine,
live order sequence, CCXT integration, idempotency, reconciliation) should be read as
requirements on the *boundary and the ledger*, not as a build list. The control plane keeps
authentication, mandates, approvals, entitlements, audit, and the product ledger.

**Housekeeping**

`Trade_Platform/ /nautilus_trader` (directory literally named with a single space) is a
duplicate Nautilus checkout. Left in place; delete when convenient.

## Constraints

- **Engine**: NautilusTrader (forked) — chosen because backtest and live share one code path,
  which is the core value and cannot be retrofitted.
- **Fork maintenance**: Track upstream `develop` and rebase regularly. The tenancy patch must
  stay thin and rebasable; upstreaming it is preferred if `nautechsystems` will take it.
- **Venue**: Binance spot only for v1. One venue, one asset class, get it boring first.
- **Stack**: Hono + Prisma + Next.js control plane (`criox4/Quant` monorepo); Rust/Python
  Nautilus engine; Python AI plane. Three languages, matching Architecture_Plan's service split.
- **Team**: 2 people. Quant-Phase estimates a credible platform at 2–3 person-years, so
  sequencing must let the deterministic spine ship independently of the AI planes.
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
| Multi-tenancy inside one runtime rather than a process per tenant | A Kubernetes deployment per customer does not scale in cost or operations for many small, mostly-idle accounts. Accepted price: a core fork that must be verified and kept rebasable. | — Pending |
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
*Last updated: 2026-09-05 after initialization*
