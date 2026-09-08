# ADR-001: Nautilus executes

**Status:** Accepted, 2026-09-08
**Decides:** Spec §10 — how orders reach the venue in live trading.
**Gates:** Phase 5. Nothing under `src/engine/live/` may exist before this.

## Decision

**Nautilus's `TradingNode` submits orders to the venue directly. Nothing else
sends a live trade.**

This is spec §10's **Option B**. The spec recommends Option A; the repo owner
chose otherwise, and the reason is the one principle the platform documents
place above all others:

> Backtest and live must run the same code path. Not "similar". The same. If
> your simulator is one codebase and your live engine is another, they will
> drift, and every drift is a strategy that behaved differently with real money
> than in the test.
> — `docs/Quant-Phase.md`

Option A satisfies that for strategy logic but breaks it precisely where money
changes hands. Under Option A, `DslStrategy` runs identically in both, but the
execution layer does not: a backtest fills through Nautilus's simulated
exchange, while live emits a `TradeIntent` to a TypeScript service that fills it
some other way. The guarantee then covers everything except the part that
decides what you actually paid.

Phase 4 is the argument for taking that seriously. Six defects were found in
the simulator, and **four of them lived in the execution path** — fill timing,
price precision, commission-aware sizing, and a halted run reporting success.
None were visible from inside; each needed an independent implementation or a
different market to surface. A second execution path, exercised only in
production and never against a reference, is where the next four would live and
where nothing would find them.

## What this costs

These are the costs. They are not hypothetical and they are not small.

### Credentials enter the Python process

The `TradingNode` holds exchange API keys. That was the strongest argument for
Option A — credential isolation is hard to retrofit — and it is now this
service's problem.

Non-negotiable consequences, each of which needs a test before any key is
loaded:

* Keys are read from a secrets manager at startup, never from a file in the
  image, never from an environment variable in a compose file, never from the
  repo.
* Keys are withdrawal-disabled and IP-allowlisted at the exchange. A key that
  can withdraw must not be creatable by this service's operators.
* Keys never appear in a log, an exception, a job record, or an HTTP response.
  The structured logger already redacts nothing by default; that changes.
* One key per account, one process per account. A process that can trade two
  accounts is a blast radius, not an optimisation.

### The risk kernel must move, or be duplicated

Spec §1 places the risk kernel in the TypeScript `trading-core`, and §10 calls
it "the sole authorization authority". If Nautilus submits directly, an order
that never passes through `trading-core` is never checked by it.

Two ways forward, and this ADR does not choose between them — that is ADR-002:

1. **Port the risk checks into a Nautilus `Actor` or execution algorithm** that
   vetoes orders before submission. The kernel becomes Python. `trading-core`
   keeps mandates, approvals and the ledger, but no longer gates orders.
2. **Keep the kernel in TypeScript and call it synchronously** before
   submitting. Preserves one implementation, but puts a network hop in the
   order path and needs an answer for what happens when it times out.

**Until that is decided and built, this service must not trade an account with
real money.** Paper trading against live data is in scope; live execution is
not.

### The platform's shape changes

`api-control` and `trading-core` no longer sit between a signal and the venue.
They keep what §9.4 gives them — the ledger, mandates, approvals, audit,
strategy versions — and this service reports to them rather than asking
permission. One writer per table still holds; this service still never opens a
connection to their PostgreSQL.

What they lose is the ability to refuse an order. That is the trade.

## What is bought

**One execution path.** The fill a backtest models and the fill live produces
come from the same engine, differing only in that one talks to a simulated
exchange and the other to a real one. Slippage attribution, live-versus-backtest
divergence tracking, and strategy-decay detection — the Layer 6 monitoring that
`Quant-Phase.md` calls the best retention play in the industry — all compare
like with like. Under Option A they would compare a simulated fill against a
fill produced by different code.

**A smaller system.** No `TradeIntent` schema, no message-bus bridge, no
idempotent inbound fill consumption, no bounded-wait-then-pause protocol for an
intent that got no answer. Spec §11 describes roughly a phase of work that this
decision deletes. Every piece of it would have been a place for the two sides to
disagree about what happened.

**Recovery that has one story.** On restart, the node reconciles its own cache
against the venue (§10.3). Under Option A it would have to reconcile against
`trading-core`'s view *and* the venue's, and decide which was right when they
differed.

## What must be true before this ships

These are the acceptance conditions for Phase 5, in addition to §10.4's:

1. ADR-002 decides where the risk kernel runs, and it is built and tested.
2. Credentials come from a secrets manager, and a test asserts they cannot
   reach a log, a job record, or an HTTP response.
3. A global kill switch stops submission for an account without needing a
   deploy, and there is a test that it does.
4. Startup reconciliation refuses to start on any discrepancy (§10.3). A node
   that trades on unverified state is worse than one that stays down.
5. The Redis cache database is on a different logical DB from arq, asserted in
   config validation. A `FLUSHDB` aimed at the job queue must never erase live
   position state.
6. `flush_on_start=False` everywhere, asserted by a test.
7. Paper trading runs for a stated period before any real key is loaded, and
   its fills are compared against a backtest over the same window — the same
   cross-engine comparison Phase 4 established, against reality this time.

## Revisiting

This decision should be revisited if the risk kernel proves impractical to run
inside the Python process, or if a jurisdiction requires that order
authorization be demonstrably independent of the system generating the orders.
Either would make Option A's separation a requirement rather than a preference.

Recorded because §10 says the choice must be explicit and written down before
any code in `live/` exists. It is now both.

---

## Addendum, 2026-09-08: condition 5 is stricter than it reads

Condition 5 above says the Redis cache database must be on a different logical
DB from arq, "asserted in config validation". Nautilus cannot do that:
`DatabaseConfig` exposes host and port and no database index (D15).

So the condition is met by running a **separate Redis instance**, and
`assert_cache_is_isolated` enforces it by comparing host and port. A differing
`/N` on the URL is explicitly *not* accepted, because it reads like compliance
and would leave both on database 0 of one instance.

This makes the condition more expensive to satisfy, not less: live trading now
requires a second Redis in the deployment.

## Addendum, 2026-09-08: environment credentials, by exception

The condition above says keys come from a secrets manager and "never from an
environment variable". **The repo owner has taken an explicit exception**, and
this records it rather than leaving the code and the ADR disagreeing — which is
the failure mode D17 through D21 were all instances of.

`NT_LIVE_ALLOW_ENV_CREDENTIALS=true` permits `EnvironmentCredentialResolver` in
live. It is **off by default**, so the rule above is still the rule; the
exception is a setting rather than a deleted check, so that it appears in a
diff, in a deployment's config, and in a WARNING on every node start.

### What the rule was protecting against

Stated plainly, because an exception taken without knowing the cost is not a
decision:

* **An environment variable is inherited by every child process.** This service
  spawns one per account (§10.1), so the key is in each of them.
* **It is readable at `/proc/<pid>/environ`** by the same user, for the life of
  the process.
* **It spreads to places nobody audits**: `docker inspect`, a compose file, CI
  logs, shell history, a crash reporter's environment dump.
* **A file has a mode.** `SecretsFileResolver` refuses one readable beyond its
  owner *before* reading it. An environment variable has nothing to check.

None of these is a reason the exception is wrong — a single-tenant box the owner
controls makes several of them uninteresting. They are the reasons it is an
exception.

### Naming

```
NT_VENUE_<REFERENCE>_KEY
NT_VENUE_<REFERENCE>_SECRET
```

`<REFERENCE>` is the account's `credentialRef`, uppercased with `-` as `_`. So
`credentialRef: "binance-main"` reads `NT_VENUE_BINANCE_MAIN_KEY` and
`NT_VENUE_BINANCE_MAIN_SECRET`.

### What has not changed

The other three consequences in this section stand and are not affected by where
the key is read from: keys are withdrawal-disabled and IP-allowlisted at the
exchange, keys never appear in a log or an HTTP response, and there is one key
per account and one process per account.

### Revisiting

The default should stay the file path. If this exception outlives the reason for
it — a single box, one operator, no CI holding the value — move back: it is one
setting and no code.

