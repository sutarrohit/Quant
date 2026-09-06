# ADR 0001: Shelve the multi-tenant runtime patch; run stock Nautilus v2, one `LiveNode` process per tenant

**Status:** Accepted
**Date:** 2026-09-06
**Decision owners:** Ashutosh Pradhan (human), per PROJECT.md Key Decisions (superseded 2026-09-05)
**Satisfies:** `FOUND-03` (D-05)

## Context

`criox4/nautilus_trader`, branch `multi-tenant-nautilus-runtime`, carries one substantive
commit — `768cbf3664` ("Add multi-tenant runtime isolation"): 1,372 lines across 18 files
introducing tenant identity (`crates/common/src/tenant.rs`, 300 lines), tenant lifecycle hosting
(`crates/live/src/tenant.rs`, 671 lines), scoped message buses, runner bindings, bounded
scheduling, and tenant-aware Redis namespaces. It touches `kernel.rs`, `msgbus`, and the Redis
cache/msgbus layer.

The original project plan assumed this patch would be rebased onto upstream `develop` and
carried forward as the mechanism for running many tenants inside one Nautilus runtime process
(density-motivated: "a Kubernetes deployment per customer does not scale for many small, idle
accounts"). Four parallel researchers, working independently against the local checkout of the
branch, converged — three of four overlapping — on the finding below: the patch is **defective**,
not merely unverified.

## Decision

**Shelve the tenancy patch. Run stock, unpatched NautilusTrader v2. Isolation between tenants is
a property of the process boundary: one `LiveNode` process per tenant.**

The submodule vendored at `vendor/nautilus_trader` is pinned to a pre-patch upstream commit
(`4692bac35bb11a25eeebb8d7af4d51c55afe53ec`, see the pin-correction note below) and carries **no
local patch of any kind**. There is no tenancy repair phase. If multi-tenant density inside one
runtime is ever needed again, the seams worth revisiting are named below; the recommendation is
to upstream them properly rather than resurrect this branch.

## Defect evidence (file:line citations, at the tenancy-patch commit `768cbf3664` /
its descendant merge `be9eaff8a7f50ec72dd54cd0cd894fdc127e69bf` on the fork's
`multi-tenant-nautilus-runtime` branch — **not** present in the vendored, pre-patch submodule)

1. **Thread-local `MessageBusScope` guard held across `.await` on a self-declared
   single-threaded host.**
   `crates/live/src/tenant.rs:259-262` enters the scope guard, then immediately
   `.await`s `self.node.start()` while the guard is still held:
   ```rust
   let _scope = MessageBusScope::enter(self.message_bus());
   self.node.start().await
   ```
   The host (`node/mod.rs`, `kernel.rs`, `runner.rs:194-226`) is documented as single-threaded;
   one of the channel senders affected by this pattern is the **order-submission channel**. A
   thread-local guard crossing an await point on a runtime that can resume the task on a
   different poll (or interleave another tenant's task on the same thread before the guard is
   released) is exactly the kind of bug that produces cross-tenant message leakage under load —
   silently, and only some of the time.

2. **Redis tenancy fails open to the legacy untenanted key.** The tenant-aware Redis namespace
   layer (`crates/infrastructure/src/redis/{cache,mod,msgbus}.rs`) falls back to the
   pre-tenancy key format when tenant context is absent, rather than refusing to proceed. A
   caller that forgets — or is never taught — to thread tenant context through does not get an
   error; it gets tenant A's data written into what looks like a global key.

3. **`TenantNamespace::key_prefix()` embeds a fresh random `runtime_instance_id` per process.**
   `crates/common/src/tenant.rs:169-176`:
   ```rust
   pub fn key_prefix(&self) -> String {
       format!(
           "nautilus:v1:tenant:{}:account:{}:runtime:{}",
           self.tenant_id,
           encode_namespace_component(self.account_id.as_ref()),
           self.runtime_instance_id
       )
   }
   ```
   Because `runtime_instance_id` is generated fresh on every process start rather than being
   stable per tenant, a crash-and-restart writes to a **new** key prefix. Crash recovery loads
   nothing — the engine believes it is flat while it is actually still holding a position on the
   venue. This is not a theoretical edge case; it is the exact failure mode a reconciliation
   layer exists to prevent, defeated by the isolation layer meant to protect it.

4. **No PyO3 surface wires tenant context through at all.**
   `crates/infrastructure/src/python/redis/cache.rs:335`:
   ```rust
   tenant_id: None,
   ```
   is hardcoded. Every Rust-side tenancy mechanism above is unreachable from the Python surface
   that `DslStrategy` and the rest of the platform actually run on.

5. **`TenantHost` starts tenants via `LiveNode::start()`, which does not drive events.**
   The lifecycle host (`crates/live/src/tenant.rs`) starts each tenant's node with
   `LiveNode::start()`. That method's own documentation
   (`crates/live/src/node/mod.rs:342-347`) states it "does not consume the runner or drive
   channel receivers." There is consequently **no multi-tenant event pump** — no component in
   the patch actually pumps data and order events for more than one tenant inside a shared
   runtime. The isolation machinery guards a code path that cannot run.

6. **Test coverage: one test.** The 671-line isolation host (`crates/live/src/tenant.rs`) ships
   exactly one test, and it asserts that a *zero* queue depth is rejected — a boundary check on
   an input validator, not a test of isolation, concurrency, or crash recovery.

Three of the four defects above (1, 3, 5) were found independently by more than one researcher
working from different angles (message-bus concurrency, crash-recovery correctness, and the
Python surface respectively) — this is what elevates the finding from "unverified" to
"defective."

## Seams worth revisiting (upstreaming candidates, not this branch)

- **`kernel.rs:101` — the kernel owning its own message bus** is a genuine structural
  improvement independent of tenancy, and would be a reasonable target for an upstream PR if
  density is ever pursued again, rather than resurrecting a forked tenancy layer on top of it.
- The idea of a **stable, deterministic namespace key** (rather than the random
  `runtime_instance_id` above) for any future per-tenant Redis scoping is worth keeping as a
  requirement; the specific implementation here is what is rejected, not the goal.
- **Bounded scheduling** and **scoped message buses** as concepts remain reasonable; this patch's
  specific wiring (items 1 and 5 above) is what does not work.

## Consequence — process-per-tenant

With the patch shelved, there is no Rust-level multi-tenant supervisor to write or maintain.
v1 has exactly two tenants (the two builders). One `LiveNode` process per tenant makes isolation
a property of the OS process boundary — provable, and free. `packages/fastapi-server` is
reserved (D-03) as the future Phase 5 supervisor surface for these per-tenant processes.

Cost of *keeping* the patch, measured at plan time: 141 upstream commits touched the patched
paths in the 90 days prior to this decision (~47/month), and the fork's own HEAD
(`be9eaff8a7`) was already a merge rather than a clean rebase — "thin and rebasable" was untrue
by the time this decision was written down.

## Preservation

The branch is not deleted — it is a record of which seams were explored and why they did not
work. It is preserved as an **annotated tag on the fork remote**:

```
archive/tenancy-768cbf3664
```

**Restore command** (recreate a local branch from the preserved tag, e.g. to inspect or extract
a seam for a future upstream PR):

```bash
git -C vendor/nautilus_trader fetch origin 'refs/tags/archive/tenancy-768cbf3664:refs/tags/archive/tenancy-768cbf3664'
git -C vendor/nautilus_trader checkout -b tenancy-archive-restore archive/tenancy-768cbf3664
```

Verify the tag exists on the remote (not merely in a local checkout) with:

```bash
git -C vendor/nautilus_trader ls-remote --tags origin 'refs/tags/archive/tenancy-768cbf3664'
```

## Pin correction at execution time (Task 1 legitimacy gate)

This plan originally specified pinning the submodule to
`be9eaff8a7f50ec72dd54cd0cd894fdc127e69bf` — the fork's `multi-tenant-nautilus-runtime` branch
HEAD. At execution, Task 1's blocking-human legitimacy gate found that commit is itself a merge
carrying the tenancy patch (`crates/common/src/tenant.rs` exists there, and it is not an
ancestor of `origin/develop`) — vendoring it would have directly violated `FOUND-01` and D-04's
"no local patch" requirement, in the same plan whose purpose is establishing that requirement.

The human decided to pin `4692bac35bb11a25eeebb8d7af4d51c55afe53ec` instead ("Pin docs.rs checks
to compatible nightly") — the last commit on the fork's `develop` branch before the tenancy patch
landed, verified to have `crates/common/src/tenant.rs` absent, `version.json` reporting
`v2.0.0rc4`, and to be an ancestor of both `origin/develop` and `origin/master`. See
`01-03-SUMMARY.md` for the full record of that gate resolution.
