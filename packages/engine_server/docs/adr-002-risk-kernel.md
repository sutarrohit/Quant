# ADR-002: The risk kernel runs in the trading process

**Status:** Accepted, 2026-09-08
**Decides:** Where account-level risk is enforced, and how authority to trade
reaches a node that cannot reach `trading-core`.
**Follows:** ADR-001, which put order submission inside this process and left
this question open.

## Decision

**The risk kernel runs inside the Python trading process, in the order path.
`trading-core` sets policy; it is never consulted to place a trade.**

Three parts, each decided rather than defaulted:

1. **Authority is pre-authorised, and does not expire.** A mandate is valid
   until `trading-core` explicitly revokes it. Nothing times out.
2. **Revocation stops new risk and nothing else.** On revoke, the account opens
   no new positions. Stops, take-profits and exits keep running.
3. **The kill switch stays exactly as Step 22 built it.** A Redis flag in *this*
   service plus a file on the node's own disk, engaged if either says so or
   either errors. `trading-core` may write to that flag like any other caller.
   It is never a dependency.

## The constraint that decided it

The repo owner set one rule, and it removes most of the option space:

> **A `trading-core` outage must not stop trading.**

That rules out a synchronous risk call before every order, which was the
obvious design and the one most platforms use. If the node has to ask
`trading-core` for permission, then `trading-core` being down means either
trading stops — forbidden — or the node trades anyway, in which case the check
was never real.

So authority has to be **held** rather than **requested**. Which makes the
question not "where is risk checked" but "what does the node already know, and
how did it come to know it".

## What a mandate is, and what it is not

A mandate is a standing statement from `trading-core`: *this account may trade,
within these limits*. It is data at rest in this service's own store, pushed
there by `trading-core` and read by the node.

The limits are already built — `RiskLimitsModel`, enforced by
`engine.live.risk.evaluate`, reaching the strategy through `engine.live.gate`.
Step 22 built the enforcement before this ADR named what it was enforcing.

**It is not a request-reply.** The node never calls `trading-core`, at startup
or otherwise. A node that needed a successful call to begin trading would stop
trading when that call failed, which is the outcome the constraint forbids.

**It is not a lease.** A lease expires unless renewed, which is a timeout by
another name.

## Why no expiry

A TTL sounds prudent and is, in this system, a disguised outage dependency. Set
it to 24 hours and a 25-hour `trading-core` outage stops trading — the exact
thing the constraint rules out, arriving a day late and looking like something
else. Any TTL is a promise that `trading-core` will be reachable within it, and
the whole premise here is that it might not be.

Revoke-only makes the failure mode explicit instead of scheduled: authority
persists until someone removes it, and if the path that would remove it is
broken, the operator uses the kill switch — which was built not to depend on
`trading-core` for exactly this reason.

This is a real trade, and the cost section states it plainly rather than
pretending the TTL was doing nothing.

## Why revocation does not flatten

Closing every position on revoke is the tidier-sounding option and the wrong
one. It converts an authority change into a **market action at whatever price
the market happens to be**, decided by a control-plane event rather than by the
strategy or the operator.

Worse, it is the same class of mistake as a kill switch that refuses exits:
letting an infrastructure state force a trade. So revocation behaves like every
other stop in this system already does —

| Mechanism | New entries | Exits |
|---|---|---|
| Risk gate stale | blocked | allowed |
| Daily loss limit hit | blocked | allowed |
| **Mandate revoked** | **blocked** | **allowed** |
| Kill switch engaged | blocked | **blocked** |

— because an account that cannot shed risk is more dangerous than one that
cannot take it on. Flattening remains available and stays an explicit act: an
operator closing a position is a decision someone made, not a timeout.

**The kill switch is the deliberate exception**, and the last row is not an
inconsistency. You reach for one when you do not trust the strategy, and a
strategy you do not trust should not be closing positions either — its idea of
an exit may be the bug. So it is a total stop, and the position becomes the
operator's to close at the exchange. That cost is exactly why it is a separate
instrument from the limits: revocation is for withdrawing authority, the kill
switch is for stopping a process you have lost confidence in.

## What this costs

### A revocation issued during an outage does not arrive

This is the sharp edge of the decision. Revocation is a write to this service's
store; if `trading-core` cannot reach it, the mandate stands and the account
keeps trading under authority its owner has withdrawn.

There is no way to have both this and "an outage must not stop trading" — a
system that fails closed on a missing revocation is a system that stops trading
when the channel breaks. The mitigation is the kill switch, which reaches a node
through two independent paths and needs neither `trading-core` nor this
service's API.

**Stated so nobody discovers it during an incident:** between `trading-core`
going down and coming back, the only way to stop an account is the kill switch.

### A stale mandate can trade indefinitely

With no expiry, a mandate nobody has looked at in six months is as valid as one
written this morning. Nothing forces a re-confirmation.

This moves a technical guarantee into an operational habit, which is a genuine
downgrade. It is accepted because the alternative is worse in a way that only
shows up during an outage. Periodic review belongs in `trading-core`'s own
processes, where a human is present.

### Policy exists in two places

`trading-core` holds the authoritative mandate; this service holds a copy it
enforces. They can disagree — during an outage, deliberately. A stored copy that
drifts from its source is a class of bug that does not exist under synchronous
checking.

Mitigated by making the copy dumb: this service never computes policy, only
applies it. The copy is data, not a second implementation.

### The audit trail is split

`trading-core` records what was authorised; this service records what was
enforced and why (`Breach`, the reason string, the values behind the decision).
Reconstructing "why did this order not go" needs both. Under a synchronous
kernel it would need one.

## What is bought

**Trading survives its control plane.** The property the owner asked for, and
the reason for everything above.

**The check is where the order is.** `engine.live.risk.evaluate` runs
microseconds before `submit_order`, on the same state the strategy just used.
A remote check races: the account can change between the answer and the send.

**It cannot be skipped.** A network call can time out, fall back, or be disabled
by a flag under load. A function call in the order path has no such failure
mode — and `NoGate`, the backtest null object, is the only path around it and
never reaches live.

**Backtest and live keep the same order path**, which is ADR-001's whole
argument extended one layer. The gate is consulted identically in both.

## What must be true before this ships

These join ADR-001's seven conditions. None is met.

1. **A mandate schema exists** and `trading-core` can write one.
2. **A revocation path exists** — `trading-core` can mark a mandate revoked in
   this service's store — with a test that a revoked mandate blocks entries and
   still permits exits.
3. **A node refuses to start without a mandate.** Absent is not permissive.
   Trading with no recorded authority is worse than not trading.
4. **The mandate's limits and the account's `RiskLimitsModel` are one thing**,
   not two that can disagree.
5. **Every block is auditable**: which limit, which values, which mandate
   revision, timestamped and retained.
6. **The two-place trade-off is written down where operators read it**, not only
   here.

## Relationship to what is already built

Step 22 built the enforcement — `engine.live.risk`, `engine.live.gate`,
`engine.live.kill_switch`, `RiskLimitsModel` on the desired state — before this
ADR named the design. That is backwards but not wrong: the code answered "how",
this answers "why, and under whose authority".

What is missing is only the mandate itself: its schema, its revocation, and the
refusal to start without one. The order path does not change.

## Revisiting

Reopen this if:

- **`trading-core` becomes highly available** to the point that a synchronous
  check is genuinely safe. Then the constraint that decided this is gone, and a
  single authoritative kernel is the better design.
- **A revocation is missed in production** and it costs something. That is the
  cost this ADR knowingly accepts; if it lands, the acceptance should be
  re-argued with the incident in hand, not from first principles.
- **A regulator or counterparty requires** an authority that provably expires.
  Revoke-only is a choice about failure modes, not a claim that it suits every
  obligation.
