# Requirements: quant-platform

**Defined:** 2026-09-05
**Core Value:** Backtest and live run the same engine, and the AI never touches credentials or order submission.

## v1 Requirements

Requirements for initial release: two operators trading their own money in Copilot mode on
Binance spot. Each maps to roadmap phases.

### Foundation

- [ ] **FOUND-01**: A stock NautilusTrader v2 `LiveNode` runs from a pinned upstream commit with no local patches
- [ ] **FOUND-02**: One `LiveNode` process serves exactly one tenant; tenant isolation is guaranteed by the process boundary
- [ ] **FOUND-03**: The tenancy branch is archived with a written record of which seams were valuable and why it was shelved
- [ ] **FOUND-04**: `StrategySpec` is a versioned JSON schema that is the single source of truth for all three languages
- [x] **FOUND-05**: `DslEvaluator` is pure Python with zero Nautilus imports, testable against a list of bars with no engine
- [x] **FOUND-06**: `DslStrategy` is the only file importing both `DslEvaluator` and Nautilus; a grep-enforceable lock-in surface
- [ ] **FOUND-07**: A golden-fixture suite proves the TypeScript validator and the Python evaluator agree on every spec
- [ ] **FOUND-08**: `AgentMandate`, `TradeIntent`, and `RiskDecision` are frozen, versioned contracts generated from one schema
- [ ] **FOUND-09**: All monetary values are decimal strings end to end; a test fails the build if a float reaches a money field

### Data

- [ ] **DATA-01**: Binance spot OHLCV is ingested from `data.binance.vision` with checksum verification
- [ ] **DATA-02**: Ingested data is stored in a `ParquetDataCatalog` the backtest engine reads natively
- [ ] **DATA-03**: A daily `exchangeInfo` snapshot is captured and retained, building point-in-time symbol history
- [ ] **DATA-04**: Delisted symbols are present in history; a backtest universe resolves to what existed on that date
- [ ] **DATA-05**: Data quality monitors flag gaps, outliers, and exchange candle restatements
- [ ] **DATA-06**: Bar timestamp semantics (open vs close) are explicit in the catalog and asserted in tests

### Strategy expression

- [ ] **DSL-01**: A user can express a strategy as a restricted JSON spec with entry, exit, and sizing rules
- [ ] **DSL-02**: A validator rejects specs that are unsupported, ambiguous, or reference unavailable indicators
- [ ] **DSL-03**: The validator rejects order types Binance does not support for the target symbol, checked against `exchangeInfo`
- [ ] **DSL-04**: The validator guarantees no lookahead is expressible in the DSL
- [ ] **DSL-05**: Every strategy edit produces a new immutable version; versions are never mutated
- [ ] **DSL-06**: A strategy version moves through DRAFT → VALIDATED → BACKTESTED → PAPER_RUNNING → PAPER_PASSED → APPROVED → LIVE → PAUSED → RETIRED, and illegal transitions are rejected

### Simulation

- [ ] **SIM-01**: A user can backtest a strategy version over a date range and see an equity curve
- [ ] **SIM-02**: Backtests are deterministic and replayable — identical input produces identical output
- [ ] **SIM-03**: The cost model applies Binance maker/taker fees, configurable slippage, and partial fills
- [ ] **SIM-04**: The same `DslEvaluator` code path runs in backtest, paper, and live; only adapters differ
- [ ] **SIM-05**: A published backtest is reproduced within tolerance, proving the foundation before anything is built on it

### Validation

- [ ] **VALID-01**: Every optimization run is recorded in a trials table (`strategy_lineage_id`, `params_hash`, `objective`, `ran_at`, `was_oos`) from the very first backtest
- [ ] **VALID-02**: Out-of-sample data is genuinely inaccessible during optimization; the lockbox is enforced, not advisory
- [ ] **VALID-03**: A user can run walk-forward analysis and see per-window results
- [ ] **VALID-04**: A user sees deflated Sharpe and probability of backtest overfitting, computed against the honest trial count
- [ ] **VALID-05**: A user can run Monte Carlo over trade ordering and see the outcome distribution
- [ ] **VALID-06**: A user sees parameter sensitivity surfaces showing whether a result is a plateau or a needle
- [ ] **VALID-07**: The UI states plainly when a strategy is likely overfit, with the evidence that says so

### Paper trading

- [ ] **PAPER-01**: A strategy version can run against live market data with simulated fills and no money
- [ ] **PAPER-02**: A strategy version cannot reach LIVE without passing a paper run; the gate is mandatory
- [ ] **PAPER-03**: Paper runs surface data feed lag, and lag is measured rather than assumed

### Control plane

- [ ] **CTRL-01**: A user can create an account, log in, and stay logged in across sessions
- [ ] **CTRL-02**: A user can connect a Binance account with trade-only, withdrawal-disabled API credentials
- [ ] **CTRL-03**: Credentials are stored envelope-encrypted — per-account DEK wrapped by KMS — and exist in plaintext only in the execution process
- [ ] **CTRL-04**: The credential schema supports Ed25519 PKCS#8 PEM keys, which Binance SBE market data requires
- [ ] **CTRL-05**: Credentials never appear in logs, error trackers, or support tooling; a redaction test enforces this
- [ ] **CTRL-06**: The AI plane has no network path to KMS or to credential storage

### Risk and mandate

- [ ] **RISK-01**: A user can create an `AgentMandate` bounding symbols, order types, sides, notional, exposure, daily loss, drawdown, and slippage
- [ ] **RISK-02**: A mandate has an explicit expiry and can be revoked instantly
- [ ] **RISK-03**: Mandate, policy, and entitlement checks run in the control plane at intent time and emit a signed `RiskDecision`
- [ ] **RISK-04**: The `RiskDecision` records every rule evaluated with observed value, limit value, and pass/fail
- [ ] **RISK-05**: A `RiskDecision` expires within seconds and cannot be reused after market, balance, position, strategy, or mandate change
- [ ] **RISK-06**: Nautilus's own `RiskEngine` remains enabled as an independent inner backstop
- [ ] **RISK-07**: A strategy cannot go live without a stop-loss when its mandate requires one

### Approval (Copilot)

- [ ] **APPR-01**: An `ApprovalGate` execution algorithm parks orders awaiting human approval without blocking the engine event loop
- [ ] **APPR-02**: The parked order is durable in the Nautilus `Cache` before the gate sees it
- [ ] **APPR-03**: A user sees the exact executable values — venue, market, side, type, quantity, price, max notional, estimated fee, max slippage, strategy version, risk checks passed, expiry
- [ ] **APPR-04**: Approval binds to a SHA-256 intent hash; changing any parameter invalidates it and forces re-evaluation
- [ ] **APPR-05**: An approval expires on a defined policy, and expiry is enforced by the engine clock
- [ ] **APPR-06**: A user receives approval requests via a Telegram bot carrying the full preview and approve/reject actions
- [ ] **APPR-07**: A user receives approval requests via web push on desktop
- [ ] **APPR-08**: An unapproved or expired order is cancelled, never silently submitted

### Execution

- [ ] **EXEC-01**: An approved order is submitted to Binance spot through the Nautilus adapter
- [ ] **EXEC-02**: The `clientOrderId` is written to Postgres before the submission call is made
- [ ] **EXEC-03**: Each submission attempt uses a fresh `clientOrderId` with recorded lineage, because Binance reuses IDs once an order leaves the book
- [ ] **EXEC-04**: An ambiguous submission is recorded as a derived `UNKNOWN` ledger state and is never blind-retried
- [ ] **EXEC-05**: Resolving an `UNKNOWN` searches open orders, closed orders, and personal trades after a settle delay before concluding no order exists
- [ ] **EXEC-06**: Copilot never auto-resubmits; an unresolved ambiguous order escalates to a human
- [ ] **EXEC-07**: Order state, fills, and positions are mirrored from Nautilus into the Postgres ledger

### Reconciliation

- [ ] **RECON-01**: Nautilus's startup reconciliation runs on every process start and its results are recorded
- [ ] **RECON-02**: The Nautilus↔Postgres leg is continuously reconciled, and drift raises an alert
- [ ] **RECON-03**: A daily out-of-band audit compares the ledger against Binance
- [ ] **RECON-04**: A manual user action at the exchange is detected and treated as an intentional override, never silently reversed
- [ ] **RECON-05**: The engine recovers correctly from a crash while holding an open position, verified by test

### Safety

- [ ] **SAFE-01**: A strategy pauses automatically on consecutive losses, excess slippage, stale data, or divergence from its backtest
- [ ] **SAFE-02**: All strategies on an account pause on daily loss limit, drawdown limit, reconciliation failure, or unresolved unknown orders
- [ ] **SAFE-03**: A platform-level kill switch disables all live execution immediately
- [ ] **SAFE-04**: A user can pause, cancel all open orders, or set reduce-only from the UI in one action
- [ ] **SAFE-05**: Position flattening is separately configurable, because automatic market exits can themselves cause loss

### Ledger and audit

- [ ] **LEDG-01**: Postgres holds the product ledger — orders, fills, positions, intents, decisions, approvals — mirrored from Nautilus
- [ ] **LEDG-02**: Every fund-affecting action is recorded append-only with actor, input hash, before/after state, versions, and trace ID
- [ ] **LEDG-03**: Nautilus's `crates/event_store` is evaluated against the audit requirement before any audit store is built
- [ ] **LEDG-04**: A user can view a complete execution timeline for any order, from signal to fill

### Monitoring

- [ ] **MON-01**: A user sees live and backtest equity curves overlaid for a deployed strategy
- [ ] **MON-02**: A user sees slippage attribution — expected versus actual fill, per trade and aggregated
- [ ] **MON-03**: `TradeIntent.marketSnapshotId` and expected price are retained specifically as the input to slippage attribution
- [ ] **MON-04**: A user is alerted when live rolling Sharpe falls outside the backtest confidence band

### AI planes

- [ ] **AI-01**: A research committee of market, news, sentiment, and portfolio analysts feeds bull and bear researchers and a research manager, producing a `SignalCandidate`
- [ ] **AI-02**: Every external fact used becomes a structured `EvidenceReference` with source, timestamps, content hash, and availability time
- [ ] **AI-03**: A `SignalCandidate` records information cutoff, model version, prompt version, and evidence bundle hash, and is reproducible
- [ ] **AI-04**: A user can describe a strategy in natural language and receive a validated `StrategySpec`
- [ ] **AI-05**: The compiler loops on validator feedback rather than emitting single-turn output
- [ ] **AI-06**: The AI plane reads portfolio state only through a sanitized snapshot with no credentials and no order authority
- [ ] **AI-07**: The AI can explain why a strategy fired, using the frozen strategy version and the evidence available at that time
- [ ] **AI-08**: The research committee is built directly on LangGraph, not on the `tradingagents` PyPI package
- [ ] **AI-09**: An LLM cannot supply or modify `tenantId`, `accountId`, `mandateId`, `idempotencyKey`, `riskDecisionId`, `approvalId`, or `clientOrderId`
- [ ] **AI-10**: Content retrieved from news and social sources is treated as untrusted input and cannot act as instructions

### Chat

- [ ] **CHAT-01**: A user can ask open questions about markets, their portfolio, their strategies, and their executions
- [ ] **CHAT-02**: Chat answers are grounded in the evidence and ledger layers and cite what they drew on
- [ ] **CHAT-03**: Chat has no order authority and no path to credentials
- [ ] **CHAT-04**: Chat ships only after the evidence and provenance layer, so it answers from real data

## v2 Requirements

Deferred to future release. Tracked but not in the current roadmap.

### Autopilot

- **AUTO-01**: A user can authorize an immutable strategy version to trade within a mandate without per-order approval
- **AUTO-02**: Agent health dashboards surface mandate consumption and automatic pause conditions
- **AUTO-03**: Strategy expiry forces periodic reauthorization

### Multi-tenancy density

- **TEN-01**: Multiple tenants share one runtime with provable isolation
- **TEN-02**: The isolation seams are upstreamed to `nautechsystems` or replaced by an orchestrator

### Expansion

- **EXP-01**: A second exchange is supported
- **EXP-02**: Margin and perpetual markets are supported, with leverage and liquidation risk modelled
- **EXP-03**: Cross-strategy correlation is surfaced (trigger: roughly 3 concurrent live strategies)
- **EXP-04**: A PineScript or LEAN importer (trigger: an actual strategy-supply problem)

### Commercial

- **COMM-01**: Billing, plans, and entitlements
- **COMM-02**: Jurisdiction rules and per-region feature gating

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Writing our own trading engine | Nautilus supplies execution truth. Binance adapter alone is 140,612 LoC. Reconsider only on the four recorded engine tripwires. |
| A second TypeScript OMS | Nautilus owns the order state machine; duplicating it yields two systems disagreeing about positions. |
| CCXT (Architecture_Plan §11) | Superseded entirely by the Nautilus Binance adapter. |
| Three-way live reconciliation | Nautilus↔Postgres is enforced; a third credentialed caller doubles blast radius for information transitivity already gives. Binance audited daily, out of band. |
| Custody or wallets | Existential security risk and a licensing question. Connect to user-owned accounts. |
| Marketplace, copy trading, social feed, leaderboards | Needs supply and trust; may read as offering securities; optimizes for luck-looking-like-skill. |
| Native mobile app | Quant work does not happen on a phone. Approval notifications ship via Telegram and web push instead. |
| Our own trading model | Frontier models plus good tooling beats a small in-house model. |
| BullMQ | A Redis enqueue outside the Postgres transaction is the dual write an outbox exists to prevent. Use `pg-boss`. |
| Kafka | Unnecessary at this throughput. |
| Temporal | Revisit for long-running workflows once the spine is boring. |
| ClickHouse / TimescaleDB | Anything the backtest engine cannot read natively is a second copy that can disagree with the simulator. `ParquetDataCatalog` + DuckDB instead. |
| Paid market data vendors | `data.binance.vision` is free, checksummed, and survivorship-free for Binance spot. |
| `tradingagents` PyPI package | Resolves to a third-party fork (`Mai0313` v0.7.0) carrying a higher version than the official 0.4.0. Build on LangGraph directly. |
| NautilusTrader v1 | The checkout is v2 (`v2.0.0rc4`); v1 receives security backports only and the two are not API-compatible. |

## Traceability

Which phases cover which requirements. Every v1 requirement maps to exactly one phase.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FOUND-01 | Phase 1 — Walking Skeleton | Pending |
| FOUND-02 | Phase 5 — Paper Trading | Pending |
| FOUND-03 | Phase 1 — Walking Skeleton | Pending |
| FOUND-04 | Phase 1 — Walking Skeleton | Pending |
| FOUND-05 | Phase 1 — Walking Skeleton | Complete |
| FOUND-06 | Phase 1 — Walking Skeleton | Complete |
| FOUND-07 | Phase 2 — Trustworthy Simulation | Pending |
| FOUND-08 | Phase 4 — Control Plane | Pending |
| FOUND-09 | Phase 1 — Walking Skeleton | Pending |
| DATA-01 | Phase 1 — Walking Skeleton | Pending |
| DATA-02 | Phase 1 — Walking Skeleton | Pending |
| DATA-03 | Phase 1 — Walking Skeleton | Pending |
| DATA-04 | Phase 2 — Trustworthy Simulation | Pending |
| DATA-05 | Phase 2 — Trustworthy Simulation | Pending |
| DATA-06 | Phase 1 — Walking Skeleton | Pending |
| DSL-01 | Phase 2 — Trustworthy Simulation | Pending |
| DSL-02 | Phase 2 — Trustworthy Simulation | Pending |
| DSL-03 | Phase 2 — Trustworthy Simulation | Pending |
| DSL-04 | Phase 2 — Trustworthy Simulation | Pending |
| DSL-05 | Phase 4 — Control Plane | Pending |
| DSL-06 | Phase 4 — Control Plane | Pending |
| SIM-01 | Phase 1 — Walking Skeleton | Pending |
| SIM-02 | Phase 1 — Walking Skeleton | Pending |
| SIM-03 | Phase 2 — Trustworthy Simulation | Pending |
| SIM-04 | Phase 1 — Walking Skeleton | Pending |
| SIM-05 | Phase 2 — Trustworthy Simulation | Pending |
| VALID-01 | Phase 1 — Walking Skeleton | Pending |
| VALID-02 | Phase 3 — Validation Evidence | Pending |
| VALID-03 | Phase 3 — Validation Evidence | Pending |
| VALID-04 | Phase 3 — Validation Evidence | Pending |
| VALID-05 | Phase 3 — Validation Evidence | Pending |
| VALID-06 | Phase 3 — Validation Evidence | Pending |
| VALID-07 | Phase 3 — Validation Evidence | Pending |
| PAPER-01 | Phase 5 — Paper Trading | Pending |
| PAPER-02 | Phase 5 — Paper Trading | Pending |
| PAPER-03 | Phase 5 — Paper Trading | Pending |
| CTRL-01 | Phase 4 — Control Plane | Pending |
| CTRL-02 | Phase 4 — Control Plane | Pending |
| CTRL-03 | Phase 4 — Control Plane | Pending |
| CTRL-04 | Phase 4 — Control Plane | Pending |
| CTRL-05 | Phase 4 — Control Plane | Pending |
| CTRL-06 | Phase 4 — Control Plane | Pending |
| RISK-01 | Phase 6 — Copilot Approval | Pending |
| RISK-02 | Phase 6 — Copilot Approval | Pending |
| RISK-03 | Phase 6 — Copilot Approval | Pending |
| RISK-04 | Phase 6 — Copilot Approval | Pending |
| RISK-05 | Phase 6 — Copilot Approval | Pending |
| RISK-06 | Phase 6 — Copilot Approval | Pending |
| RISK-07 | Phase 6 — Copilot Approval | Pending |
| APPR-01 | Phase 6 — Copilot Approval | Pending |
| APPR-02 | Phase 6 — Copilot Approval | Pending |
| APPR-03 | Phase 6 — Copilot Approval | Pending |
| APPR-04 | Phase 6 — Copilot Approval | Pending |
| APPR-05 | Phase 6 — Copilot Approval | Pending |
| APPR-06 | Phase 6 — Copilot Approval | Pending |
| APPR-07 | Phase 6 — Copilot Approval | Pending |
| APPR-08 | Phase 6 — Copilot Approval | Pending |
| EXEC-01 | Phase 8 — First Live Order | Pending |
| EXEC-02 | Phase 8 — First Live Order | Pending |
| EXEC-03 | Phase 8 — First Live Order | Pending |
| EXEC-04 | Phase 8 — First Live Order | Pending |
| EXEC-05 | Phase 8 — First Live Order | Pending |
| EXEC-06 | Phase 8 — First Live Order | Pending |
| EXEC-07 | Phase 5 — Paper Trading | Pending |
| RECON-01 | Phase 5 — Paper Trading | Pending |
| RECON-02 | Phase 7 — Safety Net | Pending |
| RECON-03 | Phase 7 — Safety Net | Pending |
| RECON-04 | Phase 7 — Safety Net | Pending |
| RECON-05 | Phase 5 — Paper Trading | Pending |
| SAFE-01 | Phase 7 — Safety Net | Pending |
| SAFE-02 | Phase 7 — Safety Net | Pending |
| SAFE-03 | Phase 7 — Safety Net | Pending |
| SAFE-04 | Phase 7 — Safety Net | Pending |
| SAFE-05 | Phase 7 — Safety Net | Pending |
| LEDG-01 | Phase 5 — Paper Trading | Pending |
| LEDG-02 | Phase 4 — Control Plane | Pending |
| LEDG-03 | Phase 4 — Control Plane | Pending |
| LEDG-04 | Phase 5 — Paper Trading | Pending |
| MON-01 | Phase 9 — Post-Deployment Monitoring | Pending |
| MON-02 | Phase 9 — Post-Deployment Monitoring | Pending |
| MON-03 | Phase 6 — Copilot Approval | Pending |
| MON-04 | Phase 9 — Post-Deployment Monitoring | Pending |
| AI-01 | Phase 11 — Research Committee | Pending |
| AI-02 | Phase 11 — Research Committee | Pending |
| AI-03 | Phase 11 — Research Committee | Pending |
| AI-04 | Phase 10 — NL → StrategySpec | Pending |
| AI-05 | Phase 10 — NL → StrategySpec | Pending |
| AI-06 | Phase 10 — NL → StrategySpec | Pending |
| AI-07 | Phase 12 — Explanation + Chat | Pending |
| AI-08 | Phase 11 — Research Committee | Pending |
| AI-09 | Phase 10 — NL → StrategySpec | Pending |
| AI-10 | Phase 11 — Research Committee | Pending |
| CHAT-01 | Phase 12 — Explanation + Chat | Pending |
| CHAT-02 | Phase 12 — Explanation + Chat | Pending |
| CHAT-03 | Phase 12 — Explanation + Chat | Pending |
| CHAT-04 | Phase 12 — Explanation + Chat | Pending |

**Coverage:**

- v1 requirements: 96 total
- Mapped to phases: 96 ✓
- Unmapped: 0
- Duplicated across phases: 0

**Phase totals:**

| Phase | Requirements | Count |
|-------|--------------|-------|
| 1 — Walking Skeleton | FOUND-01, FOUND-03, FOUND-04, FOUND-05, FOUND-06, FOUND-09, DATA-01, DATA-02, DATA-03, DATA-06, SIM-01, SIM-02, SIM-04, VALID-01 | 14 |
| 2 — Trustworthy Simulation | FOUND-07, DSL-01, DSL-02, DSL-03, DSL-04, DATA-04, DATA-05, SIM-03, SIM-05 | 9 |
| 3 — Validation Evidence | VALID-02, VALID-03, VALID-04, VALID-05, VALID-06, VALID-07 | 6 |
| 4 — Control Plane | FOUND-08, CTRL-01, CTRL-02, CTRL-03, CTRL-04, CTRL-05, CTRL-06, DSL-05, DSL-06, LEDG-02, LEDG-03 | 11 |
| 5 — Paper Trading | FOUND-02, PAPER-01, PAPER-02, PAPER-03, LEDG-01, LEDG-04, EXEC-07, RECON-01, RECON-05 | 9 |
| 6 — Copilot Approval | RISK-01, RISK-02, RISK-03, RISK-04, RISK-05, RISK-06, RISK-07, APPR-01, APPR-02, APPR-03, APPR-04, APPR-05, APPR-06, APPR-07, APPR-08, MON-03 | 16 |
| 7 — Safety Net | RECON-02, RECON-03, RECON-04, SAFE-01, SAFE-02, SAFE-03, SAFE-04, SAFE-05 | 8 |
| 8 — First Live Order | EXEC-01, EXEC-02, EXEC-03, EXEC-04, EXEC-05, EXEC-06 | 6 |
| 9 — Post-Deployment Monitoring | MON-01, MON-02, MON-04 | 3 |
| 10 — NL → StrategySpec | AI-04, AI-05, AI-06, AI-09 | 4 |
| 11 — Research Committee | AI-01, AI-02, AI-03, AI-08, AI-10 | 5 |
| 12 — Explanation + Chat | AI-07, CHAT-01, CHAT-02, CHAT-03, CHAT-04 | 5 |

**First-live-order gate:** Phases 1, 2, 4, 5, 6, 7 must all be complete before Phase 8's real
order. Phase 3 is deliberately *not* a gate.

**Non-backfillable, mapped to the earliest phase that can host them:** `DATA-03` and `VALID-01`
(Phase 1); `MON-03` (Phase 6 — the first phase in which a `TradeIntent` exists; its fields are
frozen into the contract in Phase 4 so they cannot be dropped later).

---
*Requirements defined: 2026-09-05*
*Last updated: 2026-09-05 after roadmap creation*
