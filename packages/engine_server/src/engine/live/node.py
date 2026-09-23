"""Running one account's strategy on live data (spec section 10.2).

Building the config is a pure function, so every safety property here is
testable without a network, a key, or a running exchange.

**The strategy config comes from the shared factory** (`strategies/config.py`),
which `backtest/builder.py` also calls. Two separate constructions would drift,
and with them the guarantee that simulation and production share a code path.

**Simulation only.** ADR-001 lists seven conditions before a real key is loaded
and none are met, so live mode raises rather than trading.
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
from typing import Any
from urllib.parse import urlparse

from nautilus_trader.common import Environment
from nautilus_trader.config import (
    CacheConfig,
    DatabaseConfig,
    LoggingConfig,
    TradingNodeConfig,
)
from nautilus_trader.model.identifiers import TraderId

from engine.errors import CacheNotIsolated, LiveNotPermitted, ReconciliationFailed
from engine.live.credentials import CredentialResolver, NoCredentialsResolver
from engine.live.desired_state import LiveStateStore
from engine.live.kill_switch import KillSwitch
from engine.live.mandate import MandateStore
from engine.live.recovery import CacheReader, VenueReader, ensure_reconciled
from engine.logging import log_context
from engine.settings import Settings
from engine.simulation.node import clients as simulation_clients
from engine.strategies.config import strategy_config
from engine.types.state import DesiredState, TradingMode

logger = logging.getLogger(__name__)

#: Spawn, never fork. The parent holds an asyncio loop, Redis connections and
#: Nautilus state, none of which survive a fork intact. The backtest runner
#: makes the same choice for the same reason.
_CONTEXT = multiprocessing.get_context("spawn")

def assert_cache_is_isolated(cache_url: str, queue_url: str) -> None:
    """The live cache must not share Redis with the job queue.

    Spec section 9.2: a FLUSHDB aimed at the job queue must never be able to
    erase live position state. The spec allows separation by logical database
    *or* instance; Nautilus allows only instance, because its DatabaseConfig
    exposes host and port and nothing else (D15). So instance it is, and this
    checks it rather than trusting a deployment to get it right.
    """
    cache, queue = urlparse(cache_url), urlparse(queue_url)
    if (cache.hostname, cache.port) == (queue.hostname, queue.port):
        raise CacheNotIsolated(
            "the Nautilus cache and the arq queue are on the same Redis instance; "
            "a FLUSHDB on the queue would erase live position state",
            details={"host": cache.hostname, "port": cache.port},
        )


def build_cache_config(settings: Settings) -> CacheConfig:
    """The cache a live node must have.

    Required here and forbidden in a backtest, for opposite reasons: without it
    a restart loses open orders and positions and recovery has nothing to
    compare the venue against; with it a backtest gains shared mutable state and
    loses determinism.
    """
    if not settings.cache_redis_url:
        raise CacheNotIsolated(
            "live trading requires NT_CACHE_REDIS_URL; without it a restart "
            "loses every open order and position"
        )
    assert_cache_is_isolated(settings.cache_redis_url, settings.redis_url)

    url = urlparse(settings.cache_redis_url)
    return CacheConfig(
        database=DatabaseConfig(
            type="redis",
            host=url.hostname or "localhost",
            port=url.port or 6379,
        ),
        encoding="msgpack",
        timestamps_as_iso8601=True,
        # NEVER True in live: it wipes exactly the state recovery depends on
        # (spec section 9.2). A test asserts this.
        flush_on_start=False,
    )


def build_node_config(
    state: DesiredState,
    settings: Settings,
    *,
    resolver: CredentialResolver | None = None,
) -> TradingNodeConfig:
    """``(desired state, settings) -> TradingNodeConfig``. No side effects."""
    if state.mode is TradingMode.LIVE:
        raise LiveNotPermitted(
            "live execution is gated on the conditions in "
            "docs/adr-001-live-execution.md, none of which are met; "
            "use SIMULATION mode",
            details={"accountId": state.account_id},
        )

    # Resolved but unused in simulation mode, so the path is exercised before it
    # matters. A simulation node holds no key.
    del resolver

    data_clients, exec_clients = simulation_clients(state)

    return TradingNodeConfig(
        # SANDBOX, not the LIVE default. Nautilus branches on this for
        # reconciliation and connection behaviour, and a node running a
        # simulated exchange while declaring itself live is asking for the two
        # to disagree (D17).
        environment=Environment.SANDBOX,
        # One node per account: an account is the unit of risk, credentials and
        # reconciliation, so it is the unit of process isolation (section 10.1).
        trader_id=TraderId(f"NT-{_trader_suffix(state.account_id)}"),
        cache=build_cache_config(settings),
        logging=LoggingConfig(log_level=settings.log_level),
        # The factories these need are registered on the node itself, in
        # `LiveNodeRunner.start` -- the builder cannot resolve them from here
        # (D17), and with none registered it logs at ERROR and continues past,
        # leaving a node that trades nothing and looks healthy.
        data_clients=data_clients,
        exec_clients=exec_clients,
        strategies=[
            strategy_config(
                instrument_id=state.instrument_id,
                bar_type=state.bar_type,
                spec=state.spec,
                strategy_version_id=state.strategy_version_id,
                spec_hash=state.spec_hash,
                # Declared by the operator, not discovered: a Binance
                # instrument from the public endpoint reports zero fees, and
                # the real ones need a key ADR-001 forbids (D20). Taker plus
                # slippage, matching backtest/builder.py exactly, so a strategy
                # is sized the same way in both.
                cost_bps=str(state.fees.cost_bps),
            )
        ],
    )


def _trader_suffix(account_id: str) -> str:
    """Nautilus trader ids are constrained; keep it short and alphanumeric."""
    cleaned = "".join(character for character in account_id if character.isalnum())
    return (cleaned or "ACCOUNT")[:20].upper()


class LiveNodeRunner:
    """Starts and stops **one OS process per account**.

    Satisfies the supervisor's `NodeRunner` protocol. The supervisor decides
    *what* should be running; this only makes it so -- and it now does so by
    spawning `engine.live.worker`, not by holding a `TradingNode` of its own.

    That is the isolation spec section 10.1 has always asked for, and it is
    load-bearing rather than tidy:

    * **A crash is contained.** A segfault in a native extension, an OOM kill,
      or an exception escaping a Cython callback ends a process. When every
      account shared one, every account shared every fatal fault.
    * **`dispose()` becomes safe.** It closes the loop it was given, which in
      a shared process was the supervisor's (D18). In the child it is the
      child's own, so a stopped node's memory is actually released.
    * **Liveness stops being an inference.** `process.is_alive()` is the
      operating system's answer, not a guess from a timestamp -- and the
      supervisor still has the heartbeat for the case that matters more, a
      process that is alive and wedged.

    The parent holds no Nautilus object at all. What crosses is JSON.
    """

    def __init__(
        self,
        settings: Settings,
        store: LiveStateStore,
        *,
        kill_switch: KillSwitch,
        mandates: MandateStore | None = None,
        resolver: CredentialResolver | None = None,
        stop_grace_seconds: float = 20.0,
        cache_reader: CacheReader | None = None,
        venue_reader: VenueReader | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        #: Required, not defaulted. A node that came up without a kill switch
        #: because one was not passed is the failure this argument exists to
        #: make impossible. The child builds its own from the same settings;
        #: this one is the parent's, and is what a test substitutes.
        self._kill_switch = kill_switch
        #: Checked before a live account is spawned. Optional only because a
        #: simulation needs no authority; a live start without one refuses.
        self._mandates = mandates
        self._resolver = resolver or NoCredentialsResolver()
        #: How long a child gets to stop on SIGTERM before it is killed.
        #:
        #: Must exceed Nautilus's own `timeout_disconnection` (10s by default),
        #: which a stopping node spends awaiting engine disconnections. A grace
        #: shorter than that turns every ordinary stop into a SIGKILL --
        #: measured at 10.3s for a healthy simulation node, so the default here
        #: is double it. Short enough, still, that a wedged child does not hold
        #: an account hostage.
        self._stop_grace_seconds = stop_grace_seconds
        # Both are needed to reconcile. Simulation has no venue state to
        # disagree with, so it does not reconcile and does not need them.
        self._cache_reader = cache_reader
        self._venue_reader = venue_reader
        self._processes: dict[str, Any] = {}

    async def start(self, state: DesiredState) -> None:
        if await self.is_running(state.account_id):
            # The supervisor may call start on something already up; saying so
            # is cheaper than a duplicate node.
            logger.debug("node already running", extra={"account_id": state.account_id})
            return
        self._processes.pop(state.account_id, None)

        with log_context(account_id=state.account_id, spec_hash=state.spec_hash):
            # In the parent, before a process is spawned: a disagreement with
            # the venue must halt the account rather than cost a process start,
            # and the readers live here.
            # In the parent, so a missing or revoked mandate surfaces as an
            # error the supervisor can record, rather than a child exiting with
            # a status code and looking like a crash (ADR-002). The child
            # checks again -- it is the one holding the key.
            if state.mode is not TradingMode.SIMULATION and self._mandates is not None:
                await self._mandates.require_active(state.account_id, state.instrument_id)
            await self._reconcile(state)
            # Validated here too, for the same reason -- a config that cannot
            # be built should fail as a `LiveNotPermitted` the supervisor can
            # act on, not as a child exiting with a status code.
            build_node_config(state, self._settings, resolver=self._resolver)

            from engine.live.worker import child

            process = _CONTEXT.Process(
                target=child,
                args=(state.model_dump_json(), self._settings.model_dump_json()),
                name=f"engine-live-{state.account_id}",
                # Not daemonic: a daemon child is killed abruptly when the
                # parent exits, which is exactly the SIGKILL path that skips
                # stopping the node. The supervisor's shutdown stops them.
                daemon=False,
            )
            process.start()
            self._processes[state.account_id] = process
            logger.info(
                "node process started",
                extra={"pid": process.pid, "mode": state.mode.value, "venue": state.venue},
            )

    async def _reconcile(self, state: DesiredState) -> None:
        """Agree with the venue before subscribing to anything.

        Spec section 10.3 fixes the order: cache, venue, compare, and only then
        start. A node that starts trading on unverified state is worse than one
        that stays down, so a disagreement raises and the supervisor halts the
        account rather than restarting it.

        Simulation has no venue state to disagree with -- the fills were
        imagined -- so it skips, loudly rather than silently.
        """
        if state.mode is TradingMode.SIMULATION:
            logger.info("simulation mode: nothing at a venue to reconcile against")
            return
        if self._cache_reader is None or self._venue_reader is None:
            raise ReconciliationFailed(
                "live trading requires a cache and a venue reader to reconcile against"
            )
        await ensure_reconciled(state.account_id, self._cache_reader, self._venue_reader)

    async def stop(self, account_id: str) -> None:
        """SIGTERM, then wait, then SIGKILL.

        The grace period is what lets the child stop its node and dispose it.
        A child that ignores SIGTERM is killed rather than waited on: an
        account that cannot be stopped is worse than one stopped abruptly, and
        the supervisor's next pass restarts it either way.
        """
        process = self._processes.pop(account_id, None)
        if process is None:
            return

        if process.is_alive():
            process.terminate()  # SIGTERM; the child handles it
            await asyncio.to_thread(process.join, self._stop_grace_seconds)

        if process.is_alive():
            logger.warning(
                "node process ignored SIGTERM; killing",
                extra={"account_id": account_id, "pid": process.pid},
            )
            process.kill()
            await asyncio.to_thread(process.join, 5)

        logger.info(
            "node process stopped",
            extra={"account_id": account_id, "exit_code": process.exitcode},
        )

    async def is_running(self, account_id: str) -> bool:
        """The operating system's answer, not an inference.

        A process that has exited is reaped here rather than left in the map,
        so `is_running` and the supervisor's view converge on the next pass
        without waiting out a heartbeat timeout.
        """
        process = self._processes.get(account_id)
        if process is None:
            return False
        if process.is_alive():
            return True
        logger.warning(
            "node process exited on its own",
            extra={"account_id": account_id, "exit_code": process.exitcode},
        )
        self._processes.pop(account_id, None)
        return False

    async def stop_all(self) -> None:
        """Stop every child. Called when the control plane itself is shutting down."""
        for account_id in list(self._processes):
            await self.stop(account_id)
