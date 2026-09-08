# Runbook: a live or simulation account

For whoever is on call. Everything here can be done with a shell and `curl`;
nothing needs a deploy.

## The one thing to know before an incident

**During a `trading-core` outage, the kill switch is the only way to stop an
account.**

Authority to trade is *held* by the node, not requested per order — that is what
lets trading survive its control plane (ADR-002). The cost is the other side of
the same coin: a revocation issued while `trading-core` cannot reach this
service's Redis **does not arrive**, and the account keeps trading under
authority its owner has withdrawn.

There is no design with both that and "an outage must not stop trading". The
kill switch exists to cover the gap, and depends on neither service.

## The three ways to stop an account, and they are different

| Instrument | New entries | Exits | Reach for it when |
|---|---|---|---|
| **Revoke the mandate** | blocked | **still run** | Authority is withdrawn. The strategy keeps managing what it holds |
| **Kill switch** | blocked | **blocked** | You do not trust the strategy. Nothing reaches the venue |
| **Stop the account** | — | — | Ordinary shutdown; the node stops cleanly |

Choosing wrongly under pressure is the failure this table exists to prevent.

### Revoke — the softer one

```bash
curl -X DELETE "$API/v1/live/$ACCOUNT/mandate" \
  -H "Authorization: Bearer $NT_INTERNAL_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"revokedBy": "your name", "reason": "why"}'
```

Takes effect within seconds, on the node's next read. Stops and take-profits
keep running, so the position can still be shed by the strategy that opened it.

Re-authorise with a **fresh** `PUT`, not by un-revoking — the record of what was
withdrawn is not edited away.

### Kill — the total stop

```bash
curl -X POST "$API/v1/live/$ACCOUNT/kill" -H "Authorization: Bearer $NT_INTERNAL_API_KEY"
```

When the API is unreachable, or Redis is:

```bash
touch /var/lib/engine-server/kill/kill-$ACCOUNT   # one account
touch /var/lib/engine-server/kill/kill-all        # everything
```

Either path is enough; both are read every few seconds; **a path that errors
counts as engaged**, because an operator who cannot be heard must not be assumed
to have said nothing.

**Nothing reaches the venue afterwards, exits included.** You reach for a kill
switch when you do not trust the strategy, and a strategy you do not trust
should not be closing positions either — its idea of an exit may be the bug.

> **The position is now yours.** Nothing is managing its stop-loss. Close it at
> the exchange rather than leaving it, or release the kill switch and let the
> strategy manage it again — but decide, do not drift.

Release with `DELETE .../kill`, or remove the file.

## Reading the state

```bash
curl -s "$API/v1/live/$ACCOUNT" -H "Authorization: Bearer $NT_INTERNAL_API_KEY" | jq
```

`desired` is what should be true, `observed` is what the supervisor last saw.

| `observed.status` | Meaning | Do |
|---|---|---|
| `RUNNING` | Node up, heartbeating | Nothing |
| `STARTING` / `RECONCILING` | Coming up | Wait one pass (~5s) |
| `STOPPED` | Asked to stop, and it did | Nothing |
| `FAILED` | Could not start | Read `observed.error`; it retries with backoff |
| `HALTED` | **Disagrees with the venue about money** | See below |

## HALTED

The node found a difference between its cache and the venue — an order the
venue has that we do not, a position quantity that does not match — and refused
to start. **This is not retried**, deliberately: a node that hammers an exchange
every five seconds while wrong is not recovering, it is being wrong faster.

1. Read `observed.error.discrepancies`. It lists every difference, not the first.
2. Decide what is true, at the exchange.
3. Clear it by **re-stating the desired state** (`PUT /v1/live/$ACCOUNT`). That
   bumps the revision, which is an operator saying "I have looked at it" — the
   one thing a supervisor cannot manufacture for itself.

A halted account can still be stopped, and stopping it is not a failure.

## An account that will not stay up

Look for `start failed; backing off` in the logs. Retries are exponential from
5s, capped at 5 minutes; the account is **deferred, never abandoned**.

A start only counts as successful once the node has run for
`NT_LIVE_HEALTHY_AFTER_SECONDS` (60s by default). A node that appears and dies
in ten seconds has not started, whatever the process table said.

```bash
journalctl -u engine-live -f | jq 'select(.account_id == "'$ACCOUNT'")'
```

The child's own failure is in the same stream — one process per account, and it
logs before it exits.

## Why an order did not go

Every refusal is one log line with everything needed:

```bash
journalctl -u engine-live | jq 'select(.message == "entry blocked by the risk gate")'
```

`breach` names which rule, `reason` gives the numbers, `mandate_id` names the
authority it was refused under, and `notional` is the order that would have
been sent.

| `breach` | Cause |
|---|---|
| `KILL_SWITCH` | Engaged — or the gate went stale, which is treated the same way |
| `MANDATE_REVOKED` | Authority withdrawn |
| `MAX_ORDER_NOTIONAL` | Single order too large |
| `MAX_POSITION_NOTIONAL` | The resulting total would be too large |
| `MAX_OPEN_POSITIONS` | Already at the limit |
| `DAILY_LOSS_LIMIT` | Today's realised loss reached the cap |

A **stale gate** reports `KILL_SWITCH` too: if the refresh loop has stopped, the
node no longer knows what the operator has said since, and stopping new risk is
the safe reading. Exits are still permitted in that case — unlike a real kill.

## Keys

Never in the repo, the image, or an environment variable — ADR-001. A key
reaches a node as a file mounted at runtime (`Secret` volume, `docker secret`,
`LoadCredential=`), owner-readable only; a file readable by group or other is
**refused rather than loaded**.

The logger redacts any field whose name looks like a secret, and
`VenueCredentials` redacts itself in `repr`. Neither is a reason to log one.

## Restarting the control plane

`systemctl restart engine-live` is safe. `SIGTERM` stops the nodes, marks them
`STOPPED` and releases their leases, so the next supervisor picks the accounts
up on its next pass rather than after a 90-second heartbeat timeout.

A `SIGKILL` skips all of that — which is what the heartbeat timeout is for.
