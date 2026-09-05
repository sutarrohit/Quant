# Project Research Summary

**Project:** Trade Platform — AI-first crypto quant platform
**Domain:** Multi-tenant crypto quant trading platform on a forked NautilusTrader v2 (Binance spot, Copilot-approved live execution)
**Researched:** 2026-09-05
**Confidence:** HIGH on the engine and fork assessment; MEDIUM on features, AI plane, and regulatory
**Sources:** `STACK.md`, `FEATURES.md`, `ARCHITECTURE.md`, `PITFALLS.md` in this directory

---

## Executive Summary

Four researchers worked independently. Three of them converged on the same conclusion without coordination: **the multi-tenancy patch (`768cbf3664`) is not "unverified" as PROJECT.md describes it — it is defective, and the defects are concrete, cited to file and line, and reproducible in principle today.** The isolation mechanism is a thread-local swap held across `.await` points on a runtime the patch's own doc comment declares single-threaded; the Redis namespacing fails open on a missing config field; the durable key embeds a fresh random UUID per process so crash recovery loads nothing; there is no PyO3 surface, so from Python the whole mechanism is off; and `TenantHost` never actually drives its tenants' event loops, so the multi-tenant runtime does not yet exist as a running thing. PROJECT.md calls this the project's riskiest artifact. The research says it is worse than that: it is the artifact that determines whether the fork is justified at all, and its verification deserves its own phase rather than one checkbox among four Foundation items.

Beyond the fork, the research is mostly good news, and mostly news about **what does not need to be built**. The fork is on NautilusTrader **v2** (`2.0.0rc4`), not v1 — which invalidates every v1-era tutorial and API name in `Architecture_Plan.md` but also means the engine already supplies things Architecture_Plan planned to hand-build: the OMS state machine, venue reconciliation (§13 is ~80% implemented, gating startup), an append-only hash-chained event store, deterministic synthetic IDs so restart replay dedupes, a mature 140k-LoC Binance spot adapter, and `ParquetDataCatalog` as a backtest-native data store. The Copilot human-in-the-loop pause — the one integration question that looked hard — has a clean native answer: an `ExecutionAlgorithm` that parks the order in the Cache and releases it on an approval message, never blocking the event loop and never touching the fork. Meanwhile the feature research falsifies two claims the project's own strategy documents rest on, and the architecture and pitfalls research jointly find three sections of `Architecture_Plan.md` that are wrong rather than merely dated.

The recommended approach: **ship v1 as one `LiveNode` per process per tenant**, either fixing the tenancy defects or deliberately disabling the tenancy code paths, and treat single-runtime multi-tenancy as a later optimization. Build the deterministic spine (data → DSL seam → backtest → control plane → engine-host → approval gate → reconciliation → live) with the AI planes strictly behind it and not starting until a live Copilot order has been placed and reconciled. The three things that cannot be retrofitted and must start on day one regardless of phase: the daily `exchangeInfo` snapshot (survivorship history is unreconstructable), the trials table in the strategy registry (trial counts cannot be backfilled), and slippage/audit logging (no backfill exists). The single largest open decision — Rust or Python hosts the Nautilus runtime — is unresolved and blocks the shape of Phase 0.

---

## THE CONVERGENT FINDING: the tenancy patch is defective

Stated once, canonically. Numbering below is **new and canonical**; the source-document IDs are given so the detail can be traced back. "Found by" counts independent researchers.

| # | Defect | Found by | Severity | Retrofit | Evidence |
|---|--------|----------|----------|----------|----------|
| **T1** | **Scope guards held across `.await`.** `MessageBusScope::enter` / `RunnerScope` are RAII thread-local swaps; they are held across await points in a runtime the patch itself documents as single-threaded. Guards restore in **drop order**, which has no relation to **interleave order**. Two tenants polled on one thread leave the thread-locals describing no tenant correctly — tenant A's `submit_order` reaches tenant B's `RiskEngine` and lands on B's Binance account. Both orders are individually valid; nothing errors. `RunnerScope` restores **seven** channel senders, one of which is `trading_command` — the order-submission channel. | **2** (ARCH D1, PITFALLS 1) | CATASTROPHIC | MUST-BE-TRUE-FROM-COMMIT-ONE | `crates/common/src/msgbus/mod.rs:+207-247`; `crates/live/src/runner.rs:194-227, +319-331`; `crates/live/src/tenant.rs:19-21, 259-262, 286-293`; `crates/live/src/node/mod.rs:352-354, ~489, 986-988`; `crates/system/src/kernel.rs:+783, +894, +1089, +1101, +1114` |
| **T2** | **Tenant scoping fails open, on three independent paths.** `tenant_id: Option<String>` defaults to `None`; the `None` branch silently falls back to the legacy unnamespaced key. Applies to the Redis **cache key**, the Redis **msgbus stream key**, and a missing `MessageBusScope` (which lazily materialises a default bus rather than erroring). A missing config field is a silent cross-tenant **merge**, not an error. Note the author correctly made `account_id` mandatory *given* `tenant_id`, but not `tenant_id` itself. | **2** (ARCH D5+D6, PITFALLS 2) | CATASTROPHIC | MUST-BE-TRUE-FROM-COMMIT-ONE | `crates/infrastructure/src/redis/cache.rs:+142-145, 194, 341-356`; `msgbus.rs:+99-102, 151, 453-466`; `crates/common/src/msgbus/mod.rs` (`get_message_bus` doc); `crates/common/src/python/cache.rs:1328` |
| **T3** | **Durable Redis key embeds a random per-process UUID.** `TenantNamespace::key_prefix()` unconditionally includes `runtime_instance_id`, sourced from `UUID4::default()` — a freshly generated random UUID. Every restart produces a new prefix; the engine reads an empty keyspace and concludes it is flat while holding a real position and live orders on Binance. Upstream deliberately gates `instance_id` behind `use_instance_id` (default `false`) for exactly this reason — the tenant path removes that gate. **This is a regression against upstream's considered behaviour**, and the patch's own test encodes the bug as intended behaviour. | **2** (ARCH D4, PITFALLS 3) | CATASTROPHIC | RETROFITTABLE-CHEAP (the incident it causes is not) | `crates/common/src/tenant.rs:170-177`; `crates/live/src/tenant.rs:168`; `crates/system/src/kernel.rs:279`; `crates/core/src/uuid.rs:229-235`; contrast `crates/infrastructure/src/redis/cache.rs:1213` vs `:1230`; bug-as-test at `cache.rs:1969` |
| **T4** | **No Python surface.** The commit touches **no** file under `crates/pyo3/`. `TenantHost`/`TenantContext`/`TenantHandle`/`TenantId`/`TenantNamespace` have no bindings; `crates/live/src/lib.rs:117` gates the module on `feature = "node"`, not `python`. The two Python-facing files the commit *does* touch hard-code `tenant_id: None, account_id: None`. **From Python, tenant-aware namespacing is unreachable**, so T2 stops being probabilistic and becomes guaranteed. | **2** (STACK flag 1 "highest-severity", PITFALLS 4) | SERIOUS (and it makes T1–T3 worse) | RETROFITTABLE-EXPENSIVE | `git show --stat 768cbf3664`; `crates/infrastructure/src/python/redis/cache.rs:335-336`; `.../msgbus.rs:60-61`; `crates/live/src/lib.rs:117` |
| **T5** | **`TenantHost` never drives tenant event loops — the multi-tenant runtime does not exist yet.** `dispatch()` handles only lifecycle commands and starts tenants via `LiveNode::start()`, whose own doc says it "does not consume the runner or drive channel receivers, so channel traffic arriving after startup is never serviced… not a lifecycle." The patch yields N *started* tenants that process nothing. There is no per-tenant event pump, and the obvious way to write one (N `run_with_mode` futures on a `LocalSet`) is **exactly the interleaving that triggers T1**. | 1 (ARCH D2) | CATASTROPHIC-in-effect (feature absent) | MUST-BE-TRUE-FROM-COMMIT-ONE | `crates/live/src/tenant.rs:340-353, 498-546`; `crates/live/src/node/mod.rs:344-347` |
| **T6** | **Three of four `TenantLimits` are declared but never enforced.** Only `max_queue_depth` is read. `max_open_orders`, `max_strategies`, `max_events_per_second` are validated non-zero and consulted nowhere. Also: nothing bounds **CPU time per tenant**, which is the resource that actually causes starvation. A limit that looks enforced and is not is worse than an absent one. | **2** (ARCH D3, PITFALLS perf traps) | SERIOUS | RETROFITTABLE-CHEAP | `crates/live/src/tenant.rs:46-55, 76-88, 437` |
| **T7** | **The patch is effectively untested.** 1,372 lines, 9 test functions, 19 assertion lines. `crates/live/src/tenant.rs` (671 lines, the actual isolation host) has **one** test, asserting `TenantLimits::validate()` rejects zero. Every security-relevant property is untested: capability forgery, cross-tenant dispatch, concurrent interleaving, restart recovery, namespace collision, fail-open. Existing tests are sequential or strictly nested and therefore prove the property the patch does not need. Coverage tooling would report these modules as "covered". | **2** (PITFALLS 5, ARCH AP4 + "what rigorous verification looks like") | SERIOUS | RETROFITTABLE-CHEAP — cheapest item on the list | `crates/common/src/tenant.rs:238-283`; `crates/common/src/msgbus/api.rs:+1732-1766`; `crates/live/src/runner.rs:+2083-2106`; `crates/infrastructure/src/redis/cache.rs:1969` |
| **T8** | **One process, one thread, all tenants — shared fate and head-of-line blocking.** Nautilus is full of `#[expect(clippy::await_holding_refcell_ref)]` justified by single-threadedness; one tenant's double-borrow panic, bad-payload `unwrap`, or OOM aborts every tenant's live runtime simultaneously. `dispatch` also `await`s each lifecycle command to completion holding `&mut self`, so one slow Binance handshake stalls every other tenant's control plane. | **2** (PITFALLS 7, STACK §1 note) | SERIOUS | RETROFITTABLE-EXPENSIVE | `crates/live/src/tenant.rs:19-21, 46-55, 499-556`; `crates/system/src/kernel.rs:1086, 1096, 1108` |
| **T9** | **`TenantHandle` is an in-process capability only** — unsigned UUID4, unpersisted, no cross-process meaning. Not a defect so much as a confirmation: authorization cannot live in the engine, it must stay in the control plane, and every control→engine command must be independently signed. | 1 (ARCH D7; corroborated by PITFALLS security table) | INFORMATIONAL | — | `crates/live/src/tenant.rs:98-108, 475, 617` |
| **T10** | **Rebase cost is measured, real, and the dangerous failure is silent.** Upstream `develop`: 1,765 commits/90 days; **142 in 90 days touching only the paths this patch modifies** (~47/month). The very next commit after the patch already merged upstream changes to `crates/common/src/live/runner.rs`. Merge conflicts are loud; a **clean merge that removes an invariant** is not — e.g. upstream adds an `await` to a currently-synchronous kernel method and T1 silently reappears with no conflict and no compile error. Also: the fork's history uses a **merge commit**, not a rebase, contradicting PROJECT.md's "keep it rebasable" constraint. Budget ~1.5–2 days/month forever = 5–10% of team capacity. | 1 (PITFALLS 6; ARCH corroborates via the rebase-CI recommendation) | SERIOUS | ongoing tax | `git rev-list` metrics; HEAD `be9eaff8a7` is a merge commit |

### What this means for the roadmap

- **T1, T2, T4, T5, T7 are the same artifact and all non-retrofittable.** They belong in a Phase 0 whose only deliverable is a verified — *or deliberately disabled* — tenancy layer plus a recorded host-language decision. Nothing else is safe to build on top.
- **The verification checkbox is mis-costed.** PROJECT.md carries this as one Foundation item among four. The pitfalls research prices it at **4–8 weeks**: fix the async scoping (or move to thread-per-tenant), close the fail-open paths, build the missing event pump, decide and build the language boundary, and write the concurrency/property/chaos suite that does not exist.
- **Write the failing concurrency test first.** It converts "unverified" into "verified broken", which is a much better place to be, and it is the regression detector that must run on every rebase.
- **Both researchers who examined it converge on the same escape hatch:** thread-per-tenant. It fixes T1 soundly, fixes T8's head-of-line blocking, gives per-tenant CPU accounting for free, and deletes ~52 of the upstream-touching `let _scope = …` insertions — which is simultaneously the biggest lever on T10's rebase cost. It only fails at thousands of tenants, which is years away.
- **Defense in depth outside the fork, cheap, do it regardless:** `ledger-writer` asserts the `tenant_id` on every event against the stream key it arrived on and halts the platform on mismatch; a periodic Redis `SCAN` alerts on any key not matching `nautilus:v1:tenant:*`; a separate Redis logical DB or ACL user per tenant so a namespace bug is a `NOPERM` error rather than a data merge. A leak inside the engine then becomes a loud alert instead of a silently misrouted order.

---

## THE UNMADE DECISION: Rust or Python hosts the Nautilus runtime

All four documents point at this and none can resolve it. It must be resolved before Phase 0 is planned, because it determines whether `crates/live/src/tenant.rs` is load-bearing or dead code — and therefore whether the fork is justified at all.

**Why it is open:** the tenancy patch is Rust-only (T4). PROJECT.md's stack line says "Rust/Python Nautilus engine". The normal way to drive Nautilus — every tutorial, the Binance adapter examples, the strategy API, and PROJECT.md's own `DslEvaluator`-in-pure-Python Key Decision — is Python. The two are currently incompatible.

| Branch | What it implies | Cost | Who argued it |
|--------|-----------------|------|---------------|
| **Rust host** | A tenant supervisor binary is a real, uncosted component: config loading, credential/KMS injection, a control surface for the Hono control plane, lifecycle. Strategies become Rust `DslStrategy` — viable *because* PROJECT.md's "sole adapter file" decision means only one file is engine-coupled, and a pure `DslEvaluator` means strategy semantics never need Python. Makes the tenancy patch load-bearing and the DSL seam pay for itself. Contradicts "Python AI plane / Python evaluator" ergonomics and adds Rust rebuild time (PROJECT.md tripwire 3) to the inner loop. | New component, unbudgeted | PITFALLS 4 ("the coherent choice") |
| **Python host** | PyO3 bindings for `tenant_id`/`account_id` and a `PyTenantHost` become mandatory work, and every T1–T3 mitigation must *also* be enforced at the Python boundary. Until then T2 is guaranteed rather than probabilistic. | Bindings + double enforcement | PITFALLS 4 |
| **Python host, tenancy shelved (recommended by STACK)** | Ship v1 as **one `LiveNode` per process per tenant**. Satisfies every functional requirement, is the shape upstream tests, and is the only shape whose Redis isolation is provable today. The patch's genuinely valuable contribution — `MessageBusScope`/`RunnerScope` removing the global-bus singleton assumption across 9 `LiveNode` entry points — is what makes multiple `LiveNode`s in one process plausible, and that part is done. Treat `TenantHost` as a later optimization gated on PyO3 bindings or plumbed Python Redis configs. | Lowest; contradicts a PROJECT.md Key Decision | STACK §1 (HIGH confidence) |

**Note the direct contradiction with PROJECT.md.** The Key Decision "Multi-tenancy inside one runtime rather than a process per tenant" is currently unreachable from Python and, per T5, unreachable from Rust too until an event pump exists. STACK's judgement: reaching for single-runtime multi-tenancy in v1 "converts PROJECT.md tripwire #1 into a certainty."

**Recommendation for the roadmap:** record the host-language decision as a PROJECT.md Key Decision before Phase 0 planning, and default to process-per-tenant for v1 unless the Rust-host branch is chosen deliberately with its supervisor binary costed.

---

## Where the research disagrees with the source documents

Explicitly, not smoothed over.

### `docs/Quant-Phase.md` — two central claims falsified

| Claim | Finding | Consequence |
|---|---|---|
| "Almost no platform ships live-vs-backtest divergence tracking" | **False.** QuantConnect has shipped **Live Reconciliation** for years: it runs an out-of-sample backtest in parallel to *every* live deployment automatically and overlays the equity curves, with fill-overlay tooling in the research environment. | The overlay is table stakes, not a differentiator. **Sell the attribution** ("your divergence is 80% slippage, 20% data lag") — which this project *can* claim more strongly than QC because live and sim run the literal same evaluator. Three of the four monitoring features survive as genuinely unoccupied: slippage attribution, decay detection, cross-strategy correlation. |
| "Almost nobody does validation properly, so validation is your differentiation" | **False as stated.** StrategyQuant X and BuildAlpha have shipped rigorous validation for years (two Monte Carlo engines, 9+ sim types, walk-forward matrix with 3D views, auto-rejecting cross checks). Minara markets walk-forward, OOS, regime slices, and automatic leakage detection *in this exact category*. Validation rigor is buyable for $/month. | The thesis survives only in a restated form, and in that form it is strong: **"We are the only party who can count your trials, and we lock the out-of-sample data so the count stays honest."** That is trial-counted DSR/PBO plus an enforced OOS lockbox. **No retail or AI-first platform surfaces DSR/PBO or trial counts** — genuinely open space. It is a retention feature with weak top-of-funnel; nobody signs up to be told they are wrong. |

A third, softer disagreement: Quant-Phase names bad data, a lying simulator, and underestimated live execution as the three killers. Correct but incomplete — Quant-Phase assumed a single-tenant engine and therefore never contemplated the tenancy patch, which is this project's fourth and worst killer. Bad data loses your own money slowly and visibly; a tenant leak has no recovery narrative.

Quant-Phase's PineScript/LEAN importer recommendation is also rejected for v1: it is a compiler project solving an empty-library problem that two builders do not have.

### `docs/Architecture_Plan.md` — sections that are wrong, not merely dated

Found by ARCHITECTURE and PITFALLS independently where noted.

| § | Finding | Severity |
|---|---|---|
| **§12 idempotency** | **`clientOrderId` is not a durable idempotency key on Binance.** Uniqueness is enforced **only among currently-open orders**; once filled/expired/cancelled the same ID is accepted again. §12 gets the ID lineage, the `UNKNOWN` state, search-before-retry, and the ban on blind retries right — but is missing five required pieces: write-ahead commit of the `clientOrderId` to Postgres *before* the HTTP request leaves; a **new** ID per resubmission with recorded lineage (reuse is what makes a double-fire invisible); a mandatory 30–60s settle delay before concluding "no order exists" (kills the in-flight race); a hard rule that `UNKNOWN` never auto-resubmits under Copilot and requires a fresh approval on a fresh intent hash; and an explicit link to §14's account-level halt. Plus a clock-skew guard (`-1021`, halt above 500ms offset) that §14 gestures at without a tolerance. | **CATASTROPHIC**, non-retrofittable (the write-ahead ordering at minimum) — PITFALLS 8 |
| **§13 reconciliation** | **Already ~80% implemented by Nautilus.** `crates/execution/src/reconciliation/mod.rs:16-41` documents exactly what §13 specifies: startup mass status, continuous open-order/position checks, partial-window fill reconstruction, external-order detection and event synthesis (§13's "manual actions are intentional overrides"), tolerance checks, and **deterministic synthetic IDs so restart replay dedupes**. Startup reconciliation gates the trader and failure aborts startup. **This is a requirement to verify, not to build.** Separately, the live three-way loop is downgraded: leg 1 (Nautilus↔Binance, built) plus leg 2 (Nautilus↔Postgres, ours) gives leg 3 by transitivity; a live leg 3 doubles the credential blast radius and rate-limit surface for no new information. Leg 3 becomes a **daily out-of-band audit from a separate read-only key**. | Structural — ARCH Q8; PITFALLS corroborates via the reconciliation-before-first-order ordering |
| **§16 permission table** | **Now false.** The table asserts "Live strategy runner: can access keys = No" and isolates `execution-worker` separately. In the Nautilus topology the runner *is* the execution worker — one process, `engine-host`, which both runs strategy code and holds plaintext Binance credentials. Requires rewriting plus explicit compensating controls: no inbound HTTP on `engine-host` (Redis stream ingress only, every command signed); private subnet with egress allowlisted to Binance and Redis; strategy code is a restricted DSL evaluated by our evaluator, **never arbitrary user Python** — which makes the DSL seam a safety control, not an ergonomics choice; KMS unwrap only at node construction, in memory, never logged or persisted. | **Security-relevant** — ARCH Q5; PITFALLS security table corroborates the KMS-boundary requirement |
| §1, §7, §9, §10, §17 | Structural supersessions, all downstream of the Nautilus decision: the SAFETY plane's OMS/portfolio/market-resolver move into `engine-host`; §7's single ~20-check risk kernel **splits** (mandate/policy in TS at intent time, money facts in Nautilus's `RiskEngine` against the live cache, enforcement in the `ApprovalGate`); §9's 13-state OMS becomes Nautilus's `OrderStatus` with §9's pre-submission states as control-plane intent states, `UNKNOWN` as a *derived* ledger state over a stale `Submitted`, and `RECONCILING` as behaviour not a state; §10's in-process sequence becomes a stream round-trip; §17's five services become four plus a worker. | Structural — ARCH |
| §11 CCXT | **Delete.** 100 lines of connection-manager/capability-registry/adapter design that `crates/adapters/binance/` implements in ~140k lines of tested Rust. | Delete — ARCH, STACK |
| §15 time-series store | **Contradicted.** §15 specifies TimescaleDB or ClickHouse. The backtest engine reads `ParquetDataCatalog` natively; any other store is a second copy that can disagree with the one the simulator actually uses. DuckDB over the same Parquet files covers ad-hoc analysis and the data-quality monitors at zero infra. Postgres for UI/ledger time series. | Structural — STACK §4 |
| §18 queue | **Self-defeating as written:** "Postgres transactional outbox + BullMQ/Redis workers". The point of the outbox is that the enqueue commits *in the same transaction* as the state change; BullMQ's enqueue is a Redis write — a dual write on the fund-affecting path. §18's own rule ("do not make monetary order state depend solely on BullMQ/Redis/Temporal") is obeyed by construction only with **pg-boss**. | Structural — STACK §8 |
| §20 Phase 1 | "Paper trading" is listed as a Phase-1 afterthought. Paper now requires `engine-host` and the full stream boundary — materially heavier. It is build step 6. | Sequencing — ARCH |

### `.planning/PROJECT.md` — contradictions with current Active requirements and Out of Scope

1. **"Multi-tenancy inside one runtime rather than a process per tenant"** (Key Decision) is currently unreachable from Python (T4) and non-functional in Rust (T5). See the unmade decision above.
2. **"Verify the multi-tenant runtime isolation patch"** (one Active checkbox) is mis-costed at ~4–8 weeks of fix-plus-test work, and the verb is wrong: the patch needs repair, not verification.
3. **"Rebase the tenancy patch onto upstream `develop` and keep it rebasable"** — the fork's current HEAD is a **merge** commit, so the patch is already becoming harder to extract as one clean commit. Rebase, not merge; consider a `format-patch` series so "still one clean commit" is a checkable property.
4. **Approval notification channel is missing from Active requirements**, and it is a hard dependency of Copilot, not a nice-to-have. It collides with the "Mobile app — quant work does not happen on a phone" Out of Scope entry. *Resolution:* build a **notification channel** (web push and/or Telegram bot), not a mobile app. Without it the v1 success metric ("both builders run Copilot trades for a sustained period") is unreachable — you cannot watch a screen for a sustained period. Every DIY bot requiring per-trade approval routes it through Telegram for exactly this reason.
5. **Cross-strategy correlation is in Active "Post-deployment monitoring"** but produces literally no signal below ~3 concurrent live strategies. Move to v1.x with an explicit trigger.
6. **AI chat is unresolved.** Architecture_Plan §17 lists `Chat` in the `web` service; Quant-Phase says do not build it for a long time. Recommendation: **artifact-scoped chat only** (this strategy, this backtest, this fill), never an open-ended market oracle — before the data layer is good enough to answer from, it is a hallucination surface attached to your brand.
7. **The append-only audit store may be a projection, not a new system.** Nautilus v2 ships `crates/event_store/` — an append-only, replayable, hash-chained log of every state-affecting message, with `redb` and memory backends. Evaluate before building. Docs warn the API surface is still evolving.
8. **"Autopilot — out of scope" needs one guard rail:** deterministic auto-approval below a notional threshold is the common industry hybrid and is **Autopilot wearing a Copilot costume**. Name it so nobody reintroduces it as a UX improvement.

---

## Key Findings

### Stack

The single fact that reframes everything: **the fork is on NautilusTrader v2 (`2.0.0rc4`), not v1.** `TradingNode` does not exist; it is `LiveNode.builder(...)`. There is no root `pyproject.toml` — the Python package moved to `python/`. v1 lives on `develop_v1` with ~3 months of security backports only. **Every Nautilus API name in Architecture_Plan and in any v1-era tutorial, blog post, or LLM completion is wrong.** `MIGRATION_V2.md` (47KB, in-repo) is the authoritative rename table and is required reading for every engine task. Budget a "v1 examples do not apply" tax. Staying on v2 is correct: the tenancy patch is written against v2 Rust crates and has no v1 equivalent. Pin an exact commit, not a tag; and never install v1 and v2 together — both import as `nautilus_trader`.

**Core technologies:**
- **NautilusTrader v2 `2.0.0rc4` @ pinned commit** — engine. Locked by PROJECT.md; RC risk accepted. Rust `1.98.0`, `maturin==1.15.0` exact, `uv >=0.12,<0.13` — all pinned in-repo, floating any breaks the build. `target/` is currently **18 GB**; provision disk.
- **Python 3.13** — engine + AI plane. Nautilus requires `>=3.12,<3.15`; 3.14 lags in the LangChain wheel ecosystem.
- **Redis 7.4+** — not a cache. `MessageBusConfig(external_streams=…, streams_prefix=…)` is the *supported, tested* engine↔control-plane seam. Do not build bespoke IPC.
- **PostgreSQL 17 + Prisma 7.8.x** — product ledger, mandates, approvals, audit, outbox. **Stay on Prisma 7**; 8.0.0-rc is npm `latest` and one RC per system is enough.
- **pg-boss 12.30.0** — replaces BullMQ. Enqueues inside the Postgres transaction; the outbox pattern *is* its native model.
- **`ParquetDataCatalog` + DuckDB + polars** — backtest-native data store, zero-infra analysis, ETL for multi-GB Binance Vision archives. No ClickHouse, no TimescaleDB in v1.
- **Zod 4 → `z.toJSONSchema()` → datamodel-code-generator → Pydantic v2** — cross-language contracts, generated artifacts committed so drift is a reviewable diff. No Protobuf. Rust needs nothing. Money is a decimal **string** everywhere.
- **AWS KMS + `node:crypto` AES-256-GCM** — envelope encryption, ~40 lines, no crypto library, no Vault. `EncryptionContext={tenantId, accountId}` on both `GenerateDataKey` and `Decrypt` gives tenant binding in CloudTrail. `kms:Decrypt` granted to the `engine-runner` role only.
- **LangGraph 1.2.11 + langchain-core 1.6.2** — own the research-committee graph.

**Two Binance gotchas that change schemas:**
1. **Ed25519 or nothing, soon.** RSA is unsupported; HMAC is deprecated and will be removed; `spot_market_data_mode` defaults to `Sbe`, which **requires Ed25519 and refuses to connect without it** (set `Json` for credential-free public data — also required for real-time spot klines and `@ticker`). **The "API secret" is a multi-line unencrypted PKCS#8 PEM, not a 64-char string.** This changes the credential column type (`text`), the KMS envelope size, and the redaction rules. Decide before the credential-storage phase.
2. **No local order-type validation.** Binance publishes a supported order-type set per symbol in `exchangeInfo`; the adapter does not filter on it. Our DSL validator must, or Copilot previews will promise orders the venue rejects.

**Market data: `data.binance.vision`, $0, verified live.** Monthly klines and aggTrades from 2017-08 with `.CHECKSUM` siblings, and **survivorship confirmed** — delisted `SALTBTC`/`BCCBTC`/`MITHUSDT`/`TCTUSDT` still return keys. But there is **no in-tree Binance Vision loader**; ingestion is ours to write, and point-in-time correctness (symbol listing universe, restatement detection, gap detection) is not free from the archive.

**Validation tooling: write it.** No adoptable library exists. `pypbo` is unmaintained, `mlfinlab` is license-encumbered, `vectorbt PRO` drags in a second backtest engine. Build `packages/validation/` on numpy+scipy — a few hundred lines. The load-bearing part is not the math, it is the **trial counter**, which lives in the strategy registry, not in a library.

**Supply-chain flag:** `pip install tradingagents` installs **version 0.7.0 published by `Mai0313`** — a third-party fork with a *higher* version number than TauricResearch's official 0.4.0. `uv add tradingagents` gets you someone else's code. Install from the official git ref or not at all.

### Features

**Table stakes (lose a user if missing, win none if present):** backtest with a real cost model; equity/drawdown/Sharpe/win-rate; paper trading on the same engine; NL → editable structured spec; trade-only-key exchange connection; immutable versioned registry; live position/order/balance view matching the exchange; per-trade approval with exact executable values and expiry; **out-of-band approval notification**; kill switch at strategy and account level; execution timeline; honest failure states surfaced (`UNKNOWN`, stale, disconnect, rate limit); data-quality visibility.

**The safety architecture is now the marketed norm, not a differentiator.** Minara's Autopilot page already sells per-asset mandate scoping, stops that "can't be silently removed", a drawdown flatten, manual override treated as intentional with "no hidden retries", non-custodial operation, and "deterministic signals, mandatory risk controls, auditable actions". Its Copilot: "you approve before anything hits the book." That is this project's entire trust chain, on a competitor's marketing page. Build it correctly; claiming it is worth nothing. Relatedly, Kraken/Binance/OKX/Coinbase/Gemini all shipped native agent toolkits in 2026 — **"an LLM can place a trade safely" is a solved, free commodity.** Nothing in this project's value should rest on it.

**Differentiators, ranked by defensibility:**
- **D1 trial-counted DSR/PBO** — only the platform that ran the optimizations can count N honestly. Not surfaced by any retail or AI-first platform. Requires the registry + a `trials` table from day one.
- **D2 enforced OOS lockbox with a look budget** — everyone recommends OOS; nobody enforces it. Turns best practice into a state machine and keeps D1 honest.
- **D3 per-trade slippage attribution** — not found shipped anywhere. Nearly free once the ledger and intent snapshots exist.
- **D4 strategy decay detection** — rolling Sharpe against the backtest confidence band. Not found shipped. The actual retention mechanic.
- **D9 parameter sensitivity surface** — plateau or needle. Highest legibility per unit of effort; ship one differentiator in v1 so v1 has a point of view.
- **D10 risk-check receipt on the approval card** — the 14 checks with observed value vs limit, not "14 checks passed". `RiskDecision.checks[]` already carries it. **Cheapest trust win in the product.**
- **D5 divergence** (attribution, not the overlay), **D7 explanation layer**, **D8 evidence provenance + information-cutoff tracking**, **D11 novelty/duplicate detection** — later.
- **D6 cross-strategy correlation** — unoccupied but worth zero at v1 scale. Defer.

**Anti-features:** marketplace/copy trading/leaderboards (the surface SEC enforcement targets — performance claims plus pooled funds); projected returns and "AI confidence: 87%"; custody; social sentiment as a live DSL input (point-in-time correctness is near-impossible, so it silently poisons backtests); continuous in-live retraining (**manufactures divergence by construction and destroys D5** — retrain as a new versioned strategy re-entering the state machine); building on exchange-native agent toolkits (inverts the trust model); open-ended market chat; multi-agent debate transcripts as a UI surface (ship the artifact — thesis, strongest opposing evidence, citations, readable in 30 seconds); PineScript importer.

**Two onboarding findings worth building:** an automated permission check that verifies withdrawals are actually disabled and fails loudly, and — since `PAPER_RUNNING → PAPER_PASSED` already exists — **make PAPER_PASSED require a minimum duration and a minimum trade count.** That is a differentiator hiding in a state machine you are already building; the documented failure is a 3-day paper run with 2 wins from 3 trades followed by a live -15%.

**On approval expiry** (the unsolved design problem): a 30-second wall-clock window is brutal for a human. Use **price-band expiry** — the approval stays valid while the market stays inside the slippage band, re-validated at approval time. The hash covers `expiresAt`, so this changes how `expiresAt` is chosen, not the binding. And time-to-approval is dominated by time-to-notice, so the notification channel matters more than the timer.

### Architecture

**Nautilus is not a library the control plane calls. It is a peer process owning a different kind of truth, and the seam is a message boundary.** Three sentences decide the architecture: (1) the engine never reads Postgres to make a trading decision — it reads only its own `Cache`; (2) the control plane never writes an order, it writes *permission*, which travels in as a signed message; (3) the human-in-the-loop pause is a Nautilus `ExecutionAlgorithm`, not a blocked call.

**Major components:**
1. **`engine-host`** (new; Rust fork + embedded Python) — LiveNode(s), `DslStrategy`, `ApprovalGate`, `RiskEngine`, `ExecEngine`, `Cache`, `Portfolio`, Binance adapter. **Owns execution truth.** Holds plaintext credentials. No inbound HTTP.
2. **`api-control`** (Hono + Prisma; grows) — absorbs `trading-core`'s authorization half: tenants, users, strategy versions and lifecycle, `AgentMandate`, `TradeIntent`, `RiskDecision`, `Approval`, audit, entitlements, kill-switch authority. **Owns authorization truth.**
3. **`ledger-writer`** (a worker inside `api-control`, not a deployable) — projects engine events into Postgres, runs reconciliation leg 2, escalates discrepancies.
4. **`ai-research`** (Python/FastAPI) — proposals, evidence, explanations. No credentials, no order authority, no path to Redis streams or KMS. Enforced at the network layer, not in code.
5. **`web`** (Next.js) — unchanged.

Five services become **four plus a worker**: `trading-core` dissolves and `execution-worker` is absorbed, because Nautilus's ExecClient *is* the execution worker and a separate one would need its own order state — the second OMS PROJECT.md forbids.

**The Copilot loop — the one integration question, and it has a clean answer.** `submit_order` does not send; it *routes*, via one of three destinations, and returns immediately. `exec_algorithm_id` is the hook. An `ApprovalGate` `ExecutionAlgorithm` receives the order in `on_order`, parks it in a dict, publishes a `TradeIntent` to the egress stream, and sets a time alert — all returning immediately, so the single-threaded event loop is never stalled. The order is **already durable in the Cache at status `Initialized`** because `cache.add_order` runs before routing, and nothing is on the wire. When the signed `ApprovalDecision` arrives on the inbound stream, the gate **recomputes the intent hash from the held order** (not from the message — this is what makes "changing any parameter invalidates the approval" actually enforceable), and releases via `risk_engine_queue_execute`. Every primitive is verified present. Rejected alternatives, each for a specific reason: `OrderEmulator` (hard-rejects non-price triggers; patching it means fork surface in a hot component), a custom `ExecutionClient` (order is already `Submitted` — poisons reconciliation), and the strategy holding the order (never cached, lost on crash).

**Backtest and paper are unaffected: the gate is simply not registered and `exec_algorithm_id = None`.** The evaluator, the strategy adapter, and the spec are the same bytes in all three environments; only wiring differs. **Any proposed change that makes the live and backtest flows structurally different should be rejected on sight** — that diagram is the core value.

**Two truths own disjoint fields**, which is what makes "who wins" answerable: order status / fills / positions / balances are Nautilus's, mirrored in Postgres; mandate validity, approval binding, strategy-version approval, tenant identity and entitlements are Postgres's, never mirrored into the engine. "Conflict" therefore always means one of three classes: a missing event (replay the stream, benign), an order with no `Approval` row (**security incident**, platform halt, page a human), or a position mismatch after full replay (account halt, Nautilus's venue reconciliation is the tiebreaker, not Postgres).

**The risk gate splits rather than relocating.** Roughly half of Architecture_Plan §7's ~20 checks cannot be correctly evaluated in TypeScript, because the control plane's view of balance and position is a lagged mirror — evaluating them there produces double-rejections and phantom allows and silently reintroduces a second position-tracking system. Mandate/policy/entitlement/idempotency checks go in `api-control` at intent time; balance sufficiency, max notional, price/quantity precision, and `TradingState` stay in Nautilus's `RiskEngine` against the authoritative cache. **The `ApprovalGate` is the enforcement point; the control plane is the decision point** — so a bug in the TS gate cannot release an order, and a bug in the gate cannot forge a mandate.

**The DSL seam is measurable and CI-enforceable.** `engine/` lives in `quant-platform`, depending on the fork as a built wheel. Nautilus-importing files: **exactly three** (`dsl_strategy.py`, `approval_gate.py`, `host/`). `grep -rl 'nautilus_trader' engine/dsl/` must be empty in CI. **No strategy, evaluator, DSL, or product code goes in the fork** — that makes it unrebasable and fires tripwire 1 for the one reason PROJECT.md says is explicitly not a tripwire. TypeScript validates shape and vocabulary and never simulates; Python implements behaviour and never re-validates shape; they meet at the generated JSON Schema and a **golden fixture set** (`{spec, bars, expected_actions}`) and nowhere else, so a behaviour disagreement is structurally impossible.

**Market data:** per-tenant subscriptions are unavoidable given the patch (each `TenantContext` owns a whole `LiveNode` → its own `DataEngine` → its own WebSocket). **Accept it for v1** — two users means two connections, and a shared feed introduces a *second* delivery path for market data, which is precisely the drift that kills trust. The upgrade path (`market-data-fanout` over the same ingress that carries approvals) exists, but **it makes T2's unvalidated ingress keys load-bearing for prices as well as approvals** — fix T2 first or a config typo feeds tenant A the wrong prices.

**Crash recovery:** Nautilus's baseline is genuinely strong (cache persisted and reloaded, startup reconciliation before the trader starts with failure aborting startup, deterministic synthetic IDs, event store with replay, parked orders surviving because `submit_order` caches before routing). **But none of it works until T3 is fixed** — a rotating Redis key means the cache is never found. Beyond that the control plane must add: a stable `runtime_instance_id` persisted per `(tenant, account)`; an `ApprovalGate` pending-map rebuild in `on_start` (Nautilus does not restore algo-internal state); **expiry of every pre-crash approval** (releasing on a decision made against a pre-crash market is a bug that looks like a feature); a `RECOVERED_UNRECONCILED` ledger state surfaced in the UI; and a control-plane veto on trader start when the ledger and recovered cache disagree materially.

### Critical Pitfalls (beyond the tenancy convergence above)

1. **`clientOrderId` is not durable idempotency on Binance** (CATASTROPHIC, non-retrofittable). See the §12 row above. The minimum non-negotiables before the first live order: write-ahead the ID to Postgres before the HTTP call; new ID per attempt with lineage; settle delay before concluding "no order exists"; `UNKNOWN` escalates to a human and never auto-resubmits; account halts while any `UNKNOWN` is unresolved.
2. **An LLM downstream of the risk gate** (CATASTROPHIC, non-retrofittable). The realistic violation is not handing an LLM keys — it is the LLM influencing an *input the gate trusts*: a compiled spec with `maxSlippageBps: 500` because the prompt said "be aggressive"; an LLM-*paraphrased* approval card where the human approves a description that does not match what executes; a `SignalCandidate` reaching a live strategy so a prompt injection in a news headline moves position sizing; an "LLM fixes the rejected order quantity" retry path. Mitigations: **type-level separation** (`UntrustedProposal` with no `From` impl to `StrategySpec` except through the validator — the compiler enforces what a reviewer will not); **the gate's limits come from the mandate, not the spec** (the spec may request tighter, never looser); the approval UI renders hashed fields **verbatim**, LLM prose alongside and visually distinguished, never in place of; an **n-of-m determinism check** on compilation at temperature 0, refusing and surfacing ambiguity when runs differ; a deterministic template round-trip rendering the compiled spec back to prose next to the user's original request; hard per-request and per-day token budgets in code, not the vendor dashboard.
3. **Binance-specific ways a backtest lies.** **Survivorship/delisting bias bites hardest** — Binance delists spot pairs continuously and they vanish from public klines; literature puts the crypto dead-token rate above 50%. **You cannot reconstruct the past universe later.** Also: listing-date look-ahead in universe selection; `closeTime = openTime + interval - 1ms` and the usable timestamp is `closeTime + 1ms` (off by one interval is a one-bar look-ahead that inflates everything — do not construct bars with `ts_init == ts_event`); exchange candle **restatements** that make the same backtest produce different results in March and June, destroying reproducibility (hash every ingested range and alert on change); zero-volume placeholder candles that look like tradeable liquidity; and fee schedules / `LOT_SIZE` / `MIN_NOTIONAL` / `PRICE_FILTER` **as of the backtest date**.
4. **"Same code path" does not mean "same behaviour."** Nautilus genuinely eliminates a large class of divergence, and the confidence that creates is what makes the remainder dangerous. What still diverges: latency — and **the Copilot human approval delay of 5–30s is unique to this product and enormous relative to any modelled latency**; queue-priority fill assumptions; partial fills (strategies with `if position == target` logic break — force partials by default in the backtest fill model); fee tier movement with 30-day volume; rate limits (429 → **418 IP ban of 2 minutes to 3 days, during which you cannot cancel a stop**); data feed lag; WebSocket gaps; and per-symbol `BREAK` status, which §14 does not mention. Log four timestamps per order (bar close, signal, approval, exchange ack) and feed measured distributions back into the backtest's latency and slippage models.
5. **Scope is 4–6 person-years, not 2–3.** Quant-Phase's 2–3 covers a *single-tenant* platform. PROJECT.md adds multi-tenancy plus verification plus rebase tax (0.5–1.0), the control plane (0.5), the NL compiler (0.3–0.5), the research committee (0.5+, and it has no natural definition of done — it is also the most fun part and will attract disproportionate effort), the explanation layer (0.2), and a ~15–20% tax for three languages across five services for two people. At 2 people that is 2–3 calendar years assuming no other job, no illness, and no dead ends. Two chronically-underestimated items: **operations** (two people means on-call with no rotation, and a Binance incident at 3am IST with an open position is a real event), and **"reproduce a published backtest"** (published results rarely specify data source, fees, or fill semantics precisely enough — expect "we reproduced the shape but not the number, and here is exactly why", which is still a pass).
6. **Regulatory framing** (SERIOUS, retrofittable-expensive; MEDIUM confidence, no lawyer consulted). Both founders are in India, so FIU-IND registration under PMLA is the live question and the obligation is described as **activity-based, not location-based**. The non-custodial posture is the strongest argument for falling outside the VDA-SP definition and is the single most valuable thing about that Out of Scope decision — but it is not settled. Product-design tripwires: the moment output reads as a **personalised recommendation** the advisory framing risk attaches, and pooling capital / sharing profits / letting one user's strategy trade another's account converts software into a collective-investment question in nearly every jurisdiction. Copilot's per-trade human approval is itself a meaningful legal fact. **Phase 0 actions:** one paid hour with Indian counsel who has done VDA work (two questions: does non-custodial order routing trigger FIU-IND? what must our output avoid saying?), plus a geo-block and ToS exclusion of US persons before any non-founder user — costs nothing now, expensive after you have US users.

---

## Non-Retrofittable Items

Distinct list, because these drive build order more than anything else. Each is either a design property whose retrofit is a rewrite, or a data/history item that cannot be backfilled.

### Design properties — must be true from commit one

| Item | Why it cannot be retrofitted | Phase |
|---|---|---|
| Tenant isolation is real (T1, T2, T5) — **or** the tenancy code paths are provably not live | Running untested isolation code in single-tenant mode and calling it verified is the failure mode. Cross-tenant order routing discovered in production is, per the recovery analysis, **arguably unrecoverable**: halt everything, reconstruct true ownership from Binance's `myTrades` (your ledger may be wrong), make users whole from your own funds, disclose, and expect not to keep them. | 0 |
| Host-language decision recorded (T4) | Determines whether the fork's tenancy code is load-bearing or dead, and therefore whether the fork is justified | 0 |
| `clientOrderId` write-ahead ordering + no ID reuse | The crash window between generating an ID and sending produces an order on Binance that nothing in your system knows about — unfindable by search, invisible to reconciliation | before first live order |
| Same-code-path backtest/live (already secured by the Nautilus decision) | Quant-Phase's #1 trust killer when absent; impossible to retrofit | secured |
| No type path from LLM output to `StrategySpec` except through the validator; mandate is the ceiling, not the spec | The boundary erodes at the edges, added later by well-meaning people for good reasons, none of which look like giving the LLM order authority | 1 (contracts) |
| Decimal strings for money, enforced by a type not a convention | Backtest and live disagree by cents that compound into different trade decisions | 1 (contracts) |
| Postgres ledger written *before* the exchange call, never after | A crash between call and write produces an untrackable live order | before first live order |
| Reconciliation running *before* the first live order | The first restart or first `UNKNOWN` is otherwise discovered by losing money instead of by an alert | before first live order |
| Point-in-time / survivorship-free universe selection (not just price history) | The universe is a function of data available at time `t`; retrofitting means re-deriving every conclusion | 1 (data) |

### History that cannot be backfilled — start these on day one regardless of which phase they "belong" to

| Item | Cost to start | Cost of not starting |
|---|---|---|
| **Daily `exchangeInfo` snapshot** stored as a time series (`onboardDate`, observed disappearance date, filters, status) | One cron job, ~1 hour | Permanently missing universe history. Every day not snapshotting is a permanently missing row. **This is the one data decision that is genuinely irreversible.** |
| **`trials` table** — `(strategy_lineage_id, params_hash, objective, ran_at, was_oos)` from the very first backtest | A table | D1 (trial-counted DSR/PBO) is cheap given the registry and **impossible to reconstruct later**. It is the entire restated differentiation thesis. |
| **Slippage attribution logging** — `TradeIntent` carries the expected price and market snapshot id; ledger carries the actual fill | Nearly free given the ledger | D3 cannot be backfilled. Do not drop `marketSnapshotId` as "unused" during implementation. |
| **Append-only audit** covering every fund-affecting action, from the first action | A table + discipline | Retrofitting audit after an incident proves nothing |
| **Incident log** — every incident gets a written timeline, even one-liners | Minutes | PROJECT.md's "zero silent failures" success metric is unmeasurable without it, and it is the only mechanism that turns a 2-person team's experience into something durable |

---

## Implications for Roadmap

The architecture research proposed a 13-step build order and the pitfalls research proposed a phase mapping; they agree. Consolidated below. **The deterministic spine (0–9) never depends on the AI planes (11).**

### Phase 0: Fork verification, repair, and the host-language decision
**Rationale:** T1/T2/T4/T5/T7 are one artifact, all non-retrofittable, and nothing else in the roadmap is safe to build on top. This is more aggressive than PROJECT.md's current ordering and the code assessment justifies it.
**Delivers:** a recorded host-language Key Decision; a failing-then-passing concurrent two-tenant interleave test; the T1 fix (thread-per-tenant strongly favoured — it also fixes T8 and shrinks T10); tenancy made non-optional at the **type** level (a `RuntimeMode` enum so the `None` branch stops existing and the compiler enforces it at every construction site); the missing per-tenant event pump (a non-async `LiveNode::pump_once` driven by explicit synchronous per-tenant turns, so no guard is ever held across a suspension point); stable `runtime_instance_id`; ingress-binding assertion at construction; `TenantLimits` enforced or deleted; rebase-not-merge hygiene with `git rerere` and grep gates; **debug-mode tenant assertions on in CI and staging**.
**Also starts here, out of band:** the daily `exchangeInfo` snapshot; the counsel hour; the geo-block and ToS; a measurement of Rust rebuild time (PROJECT.md tripwire 3 — measure it in week one; a slow loop for two people is an existential product risk, not an annoyance).
**Avoids:** T1–T8, plus the "ship with one tenant and defer verification" debt pattern (the verification never happens, because it is never urgent until it is too late).
**Exit gate:** two-tenant adversarial suite green, running on **every** rebase onto upstream `develop`; `kill -9` with an open position restores that position; a Redis `SCAN` finds zero unnamespaced keys. **Or:** tenancy code paths provably disabled and v1 declared process-per-tenant.
**Alternative exit, if the Rust-host branch is rejected:** ship process-per-tenant, shelve `TenantHost`, and reduce Phase 0 to T2/T3 plus the disable-and-prove work. This is STACK's recommendation and it is materially cheaper.

### Phase 1: Contracts freeze
**Rationale:** small, and it blocks the DSL seam, the control plane, and the AI planes. Whoever is not on Phase 0 should take it first.
**Delivers:** the six contracts as Zod 4 with generated JSON Schema and Pydantic committed; `intent_hash` canonicalization; the approval signature scheme; `UntrustedProposal` as a distinct type with no conversion path; decimal-string money enforced by type; **the trials-table schema decision**.
**Avoids:** pitfall 9 (LLM downstream of the gate) at the type level; float-for-money.
**Exit gate:** regeneration is a CI no-op; golden fixtures exist.

### Phase 2: Data layer
**Rationale:** longest-lead item alongside Phase 0, with no dependency on it — start both immediately. Every number downstream is garbage without it.
**Delivers:** Binance Vision ingestion (zip → polars → Nautilus wranglers → `ParquetDataCatalog`); the `symbol_listing` PIT universe; restatement detection by trailing-window checksum; gap and outlier monitors as DuckDB SQL over the catalog.
**Avoids:** pitfall 10 in full.
**Exit gate:** monitors firing on real history; `min_days_since_listing` filter available; identical results across re-runs.

### Phase 3: DSL seam
**Delivers:** `StrategySpec` + pure `DslEvaluator` + golden fixtures, zero Nautilus imports.
**Exit gate:** `grep -rl nautilus_trader engine/dsl/` empty in CI; evaluator tests run in milliseconds without an engine.

### Phase 4: Backtest path
**Delivers:** the `DslStrategy` adapter over Nautilus's BacktestEngine on Phase 2 data, with a fill model that partials by default.
**Exit gate:** **reproduce a published backtest within tolerance.** Quant-Phase's foundation acceptance test and PROJECT.md engine tripwire 4. Budget weeks; expect "the shape but not the number, and here is why."

### Phase 5: Control-plane spine
**Delivers:** the trading domain in Prisma (today: 4 auth models, no trading domain); registry state machine DRAFT→…→RETIRED **with the trials table**; encrypted credential storage sized for a **multi-line Ed25519 PEM** with a JSONB `{v, iv, tag, ct, wrappedDek}` envelope; pino redaction configured before the first credential is stored; append-only audit — **after evaluating whether Nautilus's `crates/event_store/` makes it a projection rather than a new system**.
**Exit gate:** registry enforces the state machine; audit is append-only and audit failure halts trading.

### Phase 6: Engine-host + stream boundary
**Delivers:** one tenant, no approval gate; `MessageBusConfig.external_streams` egress → `ledger-writer` → Postgres; signed inbound commands (three families only: lifecycle, approval decision, control action); paper trading on Binance spot testnet. **Note this is materially heavier than Architecture_Plan §20 assumed.**
**Exit gate:** ledger matches engine state across a multi-day paper run; `tenant_id` assertion against stream key active.

### Phase 7: Approval gate
**Delivers:** the `ApprovalGate` `ExecutionAlgorithm`; the TS mandate gate; approval UI with **D10's itemized risk-check receipt** and hashed fields rendered verbatim; **price-band expiry**; the **notification channel** (web push and/or Telegram — currently missing from Active requirements and a hard Copilot dependency); restart pending-map rebuild and pre-crash approval expiry.
**Exit gate:** every testnet order requires approval; a tampered preview fails the hash check; an approval survives a restart only by being re-requested.

### Phase 8: Reconciliation leg 2 + kill switches
**Delivers:** discrepancy taxonomy and detector; `SetTradingState(Halted|Reducing)` path; the three breaker levels; `UNKNOWN` handling with account halt and human escalation; clock-skew monitoring against Binance server time with a 500ms halt threshold; `X-MBX-USED-WEIGHT-*` tracking with per-strategy weight budgeting **at the gate** (a strategy whose steady-state weight exceeds its allocation is rejected before it runs, not after it bans you); per-symbol `BREAK` status as a strategy-level breaker.
**Note:** leg 1 is **verify, not build**. Leg 3 is a daily out-of-band audit from a separate read-only key.
**Exit gate:** injected drift triggers a halt within one cycle; every breaker has been **fired deliberately in staging** (an untested breaker is a comment); the kill switch works with Postgres down, with Redis down, and with the engine unresponsive.

### Phase 9: Live Copilot, real money, small size
**Rationale:** PROJECT.md's success metric. Position size capped at an amount you would be content to lose entirely to a bug — start smaller than feels worth it; the first live orders exist to find bugs, not returns.
**Prerequisite:** every item in PITFALLS.md's operational-readiness list, plus the four paging alerts (reconciliation drift, unresolved `UNKNOWN`, breaker fired, engine heartbeat lost) reaching a phone that wakes you, plus the runbook written **before** you need it.
**Exit gate:** sustained live running with zero silent failures.

### Phase 10: Validation suite — runs in parallel with 6–9, does not block live
**Delivers:** `packages/validation/` on numpy+scipy — walk-forward, enforced OOS lockbox (D2), **D9 parameter sensitivity surface** (ship this in v1 so v1 has a point of view), Monte Carlo on trade ordering, deflated Sharpe and PBO with the platform's own trial count (D1).

### Phase 11: AI planes — parallel with 6–10; **nothing in 6–9 may depend on this**
**Hard gate from the pitfalls research:** do not start until a live Copilot order has been placed and reconciled. The research committee has no natural definition of done and is the most fun part of the project; timebox it hard.
**Delivers:** NL→`StrategySpec` compiler with the validator-error feedback loop (the 70%→95% pass-rate delta is entirely in that loop); the committee as our own LangGraph graph with Postgres checkpoints, lifting TradingAgents' design under Apache-2.0 but never depending on it; D8 provenance and information-cutoff tracking; D7 explanation layer.

### Phase 12: Post-deployment monitoring
**Delivers:** D3 slippage attribution (**log it from the first live order — it cannot be backfilled**, so the logging lands in Phase 9 even though the product surface lands here), D5 divergence with attribution, D4 decay detection, D6 correlation (deferred until 3+ concurrent live strategies).

### Phase Ordering Rationale

- **Phase 0 gates everything** because T1/T2/T4/T5 are non-retrofittable and their failure mode has no recovery narrative.
- **Phases 0 and 2 have no dependency on each other and are the two longest-lead items — start both immediately.** Phase 1 is small and blocks 3, 5, and 11, so it goes first in whichever stream picks it up. Whoever is not on the fork can carry 1→3→4 all the way to the backtest reproduction gate without ever touching Rust. That is the right parallelism for two people.
- **Phase 4 before Phase 6** because reproducing a published backtest is the honesty gate for everything the product claims, and it is engine tripwire 4.
- **Phase 8 before Phase 9** because reconciliation must exist before the first live order — otherwise T3's restart failure and pitfall 8's double-fire are discovered by losing money rather than by an alert.
- **Divergence measurement is a Phase 9 gate, not a Phase 12 feature.** It is the instrument you need *before* real capital, not after.
- **The AI planes are strictly last on the critical path** and PROJECT.md already records this; the risk is drift, not disagreement.

### Research Flags

Phases likely needing `--research-phase` during planning:
- **Phase 0** — the event-pump redesign and the async-scoping fix are genuine engine work with no external precedent; the host-language decision has cost implications nobody has priced.
- **Phase 2** — survivorship-free Binance symbol history is harder than it sounds, and the ingestion loader does not exist in-tree.
- **Phase 7** — approval-gate restart semantics, intent-hash canonicalization, and price-band expiry design are all unsolved here.
- **Phase 8** — the discrepancy taxonomy and the `UNKNOWN` resolution protocol (settle delays, search windows, clock-skew tolerance) need to be specified before they are built.
- **Phase 11** — the AI plane is the lowest-confidence research area and the ecosystem is moving.

Phases with standard patterns (skip research):
- **Phase 1** (Zod→JSON Schema→Pydantic is a well-worn pipeline), **Phase 3** (pure-function evaluator with golden fixtures), **Phase 5** (CRUD, a state machine, and KMS envelope encryption — all documented and ~40 lines for the crypto).

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | **HIGH** for the engine and control planes | Verified against the local checkout at `be9eaff8a7` with file:line citations, plus pinned manifests and live registry queries. **MEDIUM** for the AI plane and validation tooling — the ecosystem is immature and there is nothing to adopt. |
| Features | **MEDIUM** | Competitor feature sets verified against vendor primary docs where possible; market-size, churn, and pricing figures are LOW and one cited churn statistic is explicitly flagged as uncorroborated and not for external use. |
| Architecture | **HIGH** for every claim about what Nautilus provides (file:line cited from the checkout); **MEDIUM** for the recommended shape — it is a design proposal, not an observed system. No external sources were needed, which is the stronger answer. |
| Pitfalls | **HIGH** for the code assessment (read directly from the fork) and for Binance API and data pitfalls (official docs plus literature); **MEDIUM** for India regulatory (fast-moving, no lawyer consulted) and for effort estimates. |

**Overall confidence: HIGH on what to do about the fork and the engine; MEDIUM on the product and market thesis.**

### Gaps to Address

- **Host language for the Nautilus runtime — unresolved, blocking.** Record as a PROJECT.md Key Decision before Phase 0 planning. See the dedicated section above.
- **Does the tenancy patch get repaired or shelved for v1?** These are different Phase 0s with materially different costs. STACK recommends shelving; PITFALLS and ARCHITECTURE cost the repair. Decide before planning Phase 0.
- **Nautilus v2 is an RC** (`2.0.0rc4`, 2026-09-02) and upstream's own stated priority #1 is "refine the Python bindings, close remaining API gaps." Pin a commit; budget API churn on every engine-touching phase.
- **v2 config objects are PyO3 `@final` types**, not Pydantic — the in-tree example strategy needs `__new__` gymnastics just to subclass `StrategyConfig`. `DslStrategy` will hit this. Budget for it; do not fight it, and do not try to unify Nautilus configs with our Pydantic contracts.
- **Does `crates/event_store/` satisfy the append-only audit requirement?** Evaluate in Phase 5 before building a parallel system. Its API surface is documented as still evolving.
- **Regulatory: FIU-IND applicability to non-custodial order routing is unsettled.** One counsel hour in Phase 0 shapes product decisions that are expensive to reverse.
- **Effort estimates are MEDIUM confidence** and the aggregate (4–6 person-years for the full Active list) is materially larger than the 2–3 PROJECT.md quotes. The Active list likely needs pruning or explicit milestone splitting, not just sequencing.
- **The AI plane's LangGraph choice is MEDIUM-HIGH**, and the supply-chain flag on PyPI `tradingagents` (a third-party fork at a higher version number than the official project) should be recorded somewhere a teammate will see it before typing `uv add`.

## Sources

### Primary (HIGH confidence)
- Local checkout of `criox4/nautilus_trader`, branch `multi-tenant-nautilus-runtime`, HEAD `be9eaff8a7`, tenancy commit `768cbf3664` — every engine and tenancy claim above cites a file and line from this checkout. Key files: `crates/common/src/tenant.rs`, `crates/live/src/tenant.rs`, `crates/common/src/msgbus/`, `crates/live/src/runner.rs`, `crates/live/src/node/mod.rs`, `crates/system/src/kernel.rs`, `crates/infrastructure/src/redis/`, `crates/infrastructure/src/python/redis/`, `crates/trading/src/{strategy,algorithm,python}/`, `crates/risk/src/engine/mod.rs`, `crates/execution/src/{reconciliation,order_emulator}/`, `crates/core/src/uuid.rs`, `MIGRATION_V2.md`, `ROADMAP.md`, `docs/integrations/binance.md`, `examples/live/binance/exec_tester.py`
- Git metrics against `origin/develop`: 1,765 commits/90d total; 142/90d on patched paths
- `quant-platform` manifests and `.planning/PROJECT.md`, `docs/Architecture_Plan.md`, `docs/Quant-Phase.md`
- PyPI JSON API, npm registry, GitHub API — queried 2026-09-05
- Live S3 listing of `data.binance.vision` (survivorship confirmed against four delisted symbols)
- Binance Spot API official docs — limits and 418 ban duration, `-1021` recvWindow semantics, `newClientOrderId` reuse after close

### Secondary (MEDIUM confidence)
- Vendor primary docs read directly: QuantConnect Live Reconciliation and Walk-Forward Optimization; Minara Strategy Studio and Autopilot; StrategyQuant cross-checks; Freqtrade/FreqAI; Composer crypto discontinuation; TradingAgents repo
- CFTC advisories on AI trading bots; SEC v. Fuller / Privvy Investments (May 2026)
- Bailey & López de Prado, "The Deflated Sharpe Ratio"; QuantCode-Bench (70–76% single-turn vs 95–98% agentic)
- Survivorship-bias literature (Univ. of St. Gallen; CoinAPI; StratBase)
- India VDA regulatory commentary (Legal500, Candour Legal, Vidhisastras) — practitioner commentary, **not primary law; verify with counsel**

### Tertiary (LOW confidence — flagged in the source documents)
- Pricing and category survey sites; exchange agent-toolkit roundups
- "73% of automated crypto trading accounts fail within six months" — single uncorroborated vendor blog. Directional only; **do not cite externally.**

---
*Research completed: 2026-09-05*
*Ready for roadmap: yes — pending the host-language decision*
