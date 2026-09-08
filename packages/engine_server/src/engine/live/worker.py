"""One account, one OS process (spec section 10.1).

The spec has said from the beginning that "an account is the unit of risk,
credentials and reconciliation, so it is the unit of process isolation", and
the code comments repeated it while every account ran in one process on one
event loop. That was not a stylistic gap. It made two failures possible:

* **`dispose()` closed the shared loop.** `TradingNode.dispose()` calls
  `loop.stop()` and `loop.close()`, which is correct under Nautilus's
  one-node-per-process assumption and catastrophic without it -- stopping one
  account would have taken the supervisor and every other account with it
  (docs/nautilus-api-notes.md D18).
* **A crash was never contained.** A segfault in a native extension, an OOM
  kill, or an exception escaping a Cython callback ends the process. Sharing
  one meant every account shared every fatal fault.

So this module is what a child process runs: build the node, attach the gate,
run, and heartbeat until told to stop. It holds one account and nothing else.

**What crossing the process boundary buys, beyond the two fixes.** The parent's
liveness check stops being a guess -- `process.is_alive()` is the operating
system's answer, not an inference from a timestamp. And `dispose()` is safe
again here, because the loop really is this account's own, so the memory a
stopped node holds is actually released.

**What it costs.** The child is spawned, not forked: the parent holds an
asyncio loop, Redis connections and Nautilus state, none of which survive a
fork intact. Spawn means a fresh interpreter and a fresh import of
`nautilus_trader`, which is seconds rather than milliseconds. An account start
is not on any hot path, and the alternative is a shared-fate process.

The state crosses as JSON, which is the same discipline the backtest runner
uses. Nothing that is not serialisable crosses -- in particular no Redis
client, no gate, and no credentials.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time
from typing import Any

import redis.asyncio as aioredis

from engine.live.desired_state import DesiredState, LiveStateStore, TradingMode
from engine.live.gate import RiskGate
from engine.live.kill_switch import (
    CompositeKillSwitch,
    FileKillSwitch,
    KillSwitch,
    RedisKillSwitch,
)
from engine.live.mandate import Mandate, MandateStore
from engine.live.node import build_node_config
from engine.logging import configure_logging, log_context
from engine.settings import Settings
from engine.simulation.node import register_factories

logger = logging.getLogger(__name__)

#: How often the child tells the supervisor it is alive. Bounded well below
#: `live_heartbeat_timeout_seconds` so an ordinary slow tick is not read as
#: death.
DEFAULT_HEARTBEAT_SECONDS = 15.0


async def attach_gate(
    node: Any, state: DesiredState, switch: KillSwitch, mandate: Mandate | None = None
) -> RiskGate:
    """Give every strategy on this node the account's risk gate.

    Nautilus builds strategies from a serialisable config, so a gate cannot
    travel in one -- it is set on the built instances instead. One gate per
    account, shared by all of its strategies, because the limits are
    account-level: five strategies each inside a per-strategy limit is one bet
    at five times the size (`Quant-Phase.md`).

    Refreshed **before** the node runs, so there is no window in which a
    strategy could submit an order against a gate that has never read its kill
    switch.
    """
    gate = RiskGate(account_id=state.account_id, limits=state.risk.to_limits())
    # A mandate, once one exists, is the single source of limits -- two copies
    # that can disagree is how an account trades inside a limit nobody set
    # (ADR-002).
    gate.apply(mandate)
    await gate.refresh(switch, time.monotonic_ns())
    for strategy in node.trader.strategies():
        if hasattr(strategy, "risk_gate"):
            strategy.risk_gate = gate
    logger.info(
        "risk gate attached",
        extra={
            "account_id": state.account_id,
            "kill_engaged": gate.kill_engaged,
            "limits_set": not gate.limits.is_unlimited,
            "mandate_id": mandate.mandate_id if mandate else None,
            "limits_from": "mandate" if mandate else "desired state",
        },
    )
    return gate


def build_kill_switch(settings: Settings, redis: Any) -> KillSwitch:
    """Both paths, because either alone is the one that is broken that day."""
    return CompositeKillSwitch(
        RedisKillSwitch(redis),
        FileKillSwitch(settings.live_kill_switch_dir),
    )


async def tend(
    gate: RiskGate,
    switch: KillSwitch,
    store: LiveStateStore,
    account_id: str,
    *,
    heartbeat_seconds: float,
    kill_switch_seconds: float,
    mandates: MandateStore | None = None,
) -> None:
    """Refresh the gate and heartbeat until cancelled.

    The two ride one loop deliberately: if this task dies, the gate stops being
    refreshed and goes stale, which stops new orders, *and* the heartbeat stops,
    which brings the supervisor. One failure, both responses.

    The interval is the shorter of the two, so an operator's kill takes effect
    in seconds while the heartbeat keeps its own cadence.
    """
    interval = min(heartbeat_seconds, kill_switch_seconds)
    elapsed = 0.0
    while True:
        await asyncio.sleep(interval)
        elapsed += interval
        await gate.refresh(switch, time.monotonic_ns())
        if mandates is not None:
            # Revocation reaches a running node the same way a kill does: by
            # being read, not by being pushed. `trading-core` writes; nothing
            # here calls it (ADR-002).
            try:
                current = await mandates.get(account_id)
            except Exception:
                # Unlike the kill switch, an unreadable mandate is *not*
                # treated as withdrawn. Authority already granted stands until
                # someone removes it -- failing closed here would stop trading
                # on a Redis blip, which is the outcome ADR-002 exists to
                # prevent. The kill switch is the brake that fails safe.
                logger.exception("could not read the mandate", extra={"account_id": account_id})
            else:
                was_revoked = gate.mandate_revoked
                gate.apply(current)
                if gate.mandate_revoked and not was_revoked:
                    logger.warning(
                        "mandate revoked; the account will open no new positions",
                        extra={"account_id": account_id},
                    )
        if elapsed + 1e-9 < heartbeat_seconds:
            continue
        elapsed = 0.0
        await store.heartbeat(account_id)


async def run_account(
    state: DesiredState,
    settings: Settings,
    *,
    stop: asyncio.Event | None = None,
    redis: Any | None = None,
) -> None:
    """Run one account until stopped. The child's whole job.

    Returns when the node stops -- by signal, by `stop`, or by cancellation --
    having stopped it cleanly first.

    **It does not call `dispose()`, and does not need to.** Disposing exists to
    release a node's memory and close its loop; this process exits immediately
    afterwards, so the operating system does both, unconditionally and without
    a timeout. That is the quiet benefit of one process per account: cleanup
    stops being something code has to get right (D18).
    """
    from nautilus_trader.live.node import TradingNode

    owns_redis = redis is None
    client = redis if redis is not None else aioredis.from_url(  # type: ignore[no-untyped-call]
        settings.redis_url, decode_responses=True
    )
    store = LiveStateStore.from_settings(settings, client)
    switch = build_kill_switch(settings, client)
    halt = stop if stop is not None else asyncio.Event()

    mandates = MandateStore(client)
    mandate = await _authority(state, mandates)

    node = TradingNode(config=build_node_config(state, settings))
    # Between construction and build, and nowhere else. A node built without
    # its factories does not raise -- it comes up with no data client and no
    # execution client and reports itself healthy (D17).
    register_factories(node, state)
    node.build()
    gate = await attach_gate(node, state, switch, mandate)

    tender = asyncio.create_task(
        tend(
            gate,
            switch,
            store,
            state.account_id,
            heartbeat_seconds=DEFAULT_HEARTBEAT_SECONDS,
            kill_switch_seconds=settings.live_kill_switch_interval_seconds,
            mandates=mandates,
        )
    )
    running = asyncio.create_task(node.run_async())
    logger.info(
        "node running",
        extra={
            "account_id": state.account_id,
            "mode": state.mode.value,
            "venue": state.venue,
            "spec_hash": state.spec_hash,
        },
    )

    try:
        # Whichever comes first, and the second one is not optional.
        #
        # Nautilus installs its **own** SIGTERM handler when the node runs, and
        # it replaces the one this module set (D19). So on a `terminate()` the
        # node shuts itself down cleanly and our stop event is never set --
        # meaning a child that waited only on the event would sit there,
        # node stopped, doing nothing, until the parent's grace period ran out
        # and SIGKILLed it. Twenty seconds per stop, and the exit code of a
        # process that was killed rather than one that finished.
        #
        # Waiting on the node's own task instead makes Nautilus's handler the
        # thing that ends this process, which is what it already is.
        finished = asyncio.ensure_future(halt.wait())
        await asyncio.wait({running, finished}, return_when=asyncio.FIRST_COMPLETED)
        finished.cancel()
    finally:
        tender.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tender
        if not running.done():
            with contextlib.suppress(Exception):
                await node.stop_async()
            running.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await running
        if owns_redis:
            await client.aclose()
        logger.info("node stopped", extra={"account_id": state.account_id})


async def _authority(state: DesiredState, mandates: MandateStore) -> Mandate | None:
    """The mandate this account trades under, if it needs one.

    **Live requires it and refuses without it.** Trading real money with no
    recorded authority is worse than not trading, and "there was no record" is
    not a defence anyone wants to give afterwards (ADR-002).

    **Simulation does not.** A mandate authorises money; a simulation has none
    to authorise, and requiring one would put a control-plane step in front of
    the mode whose whole purpose is being easy to run. If one happens to exist
    it is still applied, so the path is exercised rather than dormant.
    """
    if state.mode is not TradingMode.SIMULATION:
        return await mandates.require_active(state.account_id, state.instrument_id)

    mandate = await mandates.get(state.account_id)
    if mandate is not None and not mandate.is_active:
        logger.warning(
            "simulating under a revoked mandate; new entries will be blocked",
            extra={"account_id": state.account_id},
        )
    return mandate


async def _main(state_json: str, settings_json: str) -> None:
    state = DesiredState.model_validate_json(state_json)
    settings = Settings.model_validate_json(settings_json)
    configure_logging(settings.log_level)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for received in (signal.SIGINT, signal.SIGTERM):
        # The parent terminates with SIGTERM. Handling it rather than dying on
        # it is what closes positions' worth of bookkeeping cleanly -- and what
        # lets `dispose()` run.
        loop.add_signal_handler(received, stop.set)

    with log_context(account_id=state.account_id, spec_hash=state.spec_hash):
        await run_account(state, settings, stop=stop)


def child(state_json: str, settings_json: str) -> None:  # pragma: no cover - spawn target
    """Subprocess entry point. Never raises into the parent.

    A child that dies is a fact the parent learns from `is_alive()` and from
    the heartbeat stopping, not from an exception -- there is no channel for
    one to cross, and inventing one would only duplicate what the supervisor
    already watches.
    """
    try:
        asyncio.run(_main(state_json, settings_json))
    except BaseException:
        logging.getLogger(__name__).exception("live node process failed")
        raise SystemExit(1) from None
