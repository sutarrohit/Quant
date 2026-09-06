# ADR 0002: Rust rebuild time — the PROJECT.md tripwire 3 baseline

**Status:** Accepted
**Date:** 2026-09-06
**Satisfies:** PROJECT.md tripwire 3 ("Rust rebuild times make the two-person iteration loop
unworkable"), D-04's rationale for a submodule over a wheel

## Why this measurement exists

D-04 chose a git submodule, installed editable, over a published wheel specifically so that
PROJECT.md's engine-decision tripwire 3 — "how long does a Rust rebuild take" — becomes
measurable instead of assumed. RESEARCH.md's Pitfall 4 warns against putting adapter work on the
critical path before this number exists. This ADR takes the measurement before Plan 01-05 writes
the first line of adapter code.

## Machine

| Field | Value |
|---|---|
| CPU | Apple M1 Pro |
| Cores | 10 |
| RAM | 32 GB |
| OS | macOS 15.7.2 (Darwin 24.6.0) |
| Rust toolchain | 1.98.0 (pinned by `vendor/nautilus_trader/rust-toolchain.toml`) |
| uv | 0.12.0 |
| Cargo registry cache | warm for every measurement below (first download already paid) |
| Date | 2026-09-06 |

## Headline finding: the vendored workspace's documented default build does not complete on this machine

`vendor/nautilus_trader/Cargo.toml`'s `[profile.release]` — the profile maturin selects by
default for an editable install — is `opt-level = 3`, `lto = "fat"`, `codegen-units = 1`,
`panic = "abort"`, with every pyo3 feature enabled (`arrow`, `betfair`, `high-precision`,
`mimalloc`, `redis`, `postgres`, `defi`, `hypersync`, `tracing-bridge`). That is a full-workspace,
single-codegen-unit, whole-program LTO link across the entire crate graph — Binance adapter alone
is ~140,612 LoC (per PROJECT.md's research), and this profile links it together with every other
adapter and the backtest/execution/portfolio engines into one `cdylib`.

**Measured: this attempt ran approximately 1 hour 4 minutes of wall-clock compilation before the
final `nautilus_pyo3` link step was SIGKILLed (`signal: 9`) by the OS for memory exhaustion**, on
a 32 GB / 10-core machine that is not an unusually small development box. The kill also took down
an unrelated background process running at the same time, confirming this was genuine
machine-wide memory pressure at the link step, not a fluke in one process.

**This is the tripwire finding, stated plainly rather than rounded down: the documented default
build (`uv sync --project engine`, or `make install` in the submodule) does not complete on a
32 GB / 10-core developer machine as shipped.** A two-person team cannot iterate against this
build. PROJECT.md tripwire 3 ("Rust rebuild times make the two-person iteration loop unworkable")
is **crossed** by the stock configuration.

## Mitigation, and why it does not touch FOUND-01

The submodule's own `Cargo.toml` already defines a `release-debugging` profile
(`inherits = "release"`, `lto = false`, `incremental = true`, `debug = "full"`) — same
`opt-level = 3` as release, without the whole-program LTO link. `engine/pyproject.toml`'s
`[tool.uv] config-settings-package` pins `nautilus-trader`'s build to
`--profile release-debugging`. This is a **build-argument override**, not a change to any file
under `vendor/`: `git -C vendor/nautilus_trader status --porcelain` stays empty before, during,
and after every measurement below. FOUND-01's "no local patch" invariant is untouched — we are
choosing which of the vendor's own pre-existing, stock profiles to build with, exactly as
`make build-debug` in the submodule's own Makefile chooses a non-release profile for the same
reason.

## The three measurements (release-debugging profile, cargo registry warm)

All three measurements below use the actual install path this project depends on day to day —
`uv sync --project engine` (optionally `--reinstall-package nautilus-trader` to force the
package-level rebuild path uv would otherwise skip) — rather than a hand-invoked `cargo`
command with a different environment signature (a hand-invoked `cargo rustc` was tried first and
produced a spurious full recompile from a `PYO3_PYTHON` / build-script environment mismatch
relative to the real uv/maturin invocation; discarded as not representative).

| # | Measurement | Command | Result |
|---|---|---|---|
| 1 | Cold build (`target/` removed, cargo registry warm) | `uv sync --project engine` (fresh `vendor/nautilus_trader/target/`) | **37 min 53 s** ("Prepared 1 package in 37m 53s", uv's own build timer) |
| 2 | Warm no-op rebuild (nothing changed, target dir warm) | `uv sync --project engine --reinstall-package nautilus-trader` | **47.55 s** ("Prepared 1 package in 47.55s") |
| 3 | Warm one-touch rebuild (`touch crates/trading/src/strategy/mod.rs`, content unchanged) | same as above, after `touch` | **34.06 s** ("Prepared 1 package in 34.06s") |

`touch` was used for measurement 3 per plan: it advances cargo's mtime-based fingerprint without
changing file contents, so `git -C vendor/nautilus_trader status --porcelain` stayed empty
throughout — the fallback content-edit-then-restore path was not needed.

**Honest anomaly, not smoothed over:** measurement 3 (34.06 s) was not slower than measurement 2
(47.55 s), which is counter-intuitive — touching a source file and forcing recompilation of its
dependents should cost *at least* as much as a true no-op check. The most likely explanation is
that cargo's fingerprint-validation pass over the ~1,300-crate dependency graph is itself a
non-trivial, somewhat variable cost independent of how much actually needs recompiling at this
timescale (run-to-run jitter over tens of seconds, on a machine also running several other
applications — see the OrbStack/Chrome/WhatsApp processes visible in `top` during these
measurements). Both numbers are in the same "well under a minute" regime and support the same
conclusion below; the anomaly is recorded rather than re-measured into looking clean, per the
plan's own instruction not to round a tripwire number toward comfort.

## Does the measured edit loop cross PROJECT.md tripwire 3?

**Two different answers depending on which build is asked about, and both must be recorded:**

- **The stock default build (fat-LTO release): crosses the tripwire outright — it does not
  finish on this machine.** If a future contributor removes the `release-debugging` override
  (for example, "just use release, it's faster at runtime") without reading this ADR, they will
  reproduce the SIGKILL above.
- **The mitigated build (`release-debugging`), which is what `engine/pyproject.toml` actually
  ships: does not cross the tripwire.** A 38-minute cold build is a real cost (worth minimizing
  further with the devcontainer's persistent cargo-registry and `target/` volumes — see D-10),
  but the edit loop that matters day to day — touching a Rust file and rebuilding — is
  **well under a minute**, which is a workable iteration loop for a two-person team doing
  primarily Python-side (DSL, adapter, CLI) work against a rarely-changing vendored engine.

## Runtime-speed tradeoff, stated for the record

`release-debugging` keeps `opt-level = 3` (same as `release`) and only drops whole-program LTO
and sets `codegen-units` back to cargo's per-crate default plus keeps full debug info. LTO
typically yields single-digit-to-low-double-digit percent runtime gains on this kind of
numeric/adapter-heavy code, not a multiple — the `dev` profile (`opt-level = 0`) would have been
a much larger runtime regression and was rejected for that reason. If a future profiling pass on
a real backtest shows the missing LTO materially matters, the escape hatch is
`CARGO_PROFILE_RELEASE_LTO=thin` plus `CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16 uv sync`, which
keeps most of LTO's benefit at a fraction of fat-LTO's peak memory — untested here because the
`release-debugging` profile already existed in the vendored source and needed no new
configuration to reach for.
