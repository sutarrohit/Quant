"""The live control plane's entry point.

    uv run python -m engine.live.main

Phase 5 built a supervisor, a node runner, a risk gate and a kill switch, and
nothing that starts them. This is the front door.

It is deliberately thin. Everything it does is construction and shutdown; every
decision lives in the objects it builds, where it is tested. What it does own is
the wiring that must not be got wrong:

* the kill switch is a **composite** of Redis and a file on this node's disk, so
  an operator keeps a path to the account when one of them is unreachable;
* the supervisor's `holder` identifies **this process**, so a lease says which
  machine holds an account rather than merely that someone does;
* a `SIGTERM` stops the nodes and releases the leases, so a deploy hands the
  accounts back in seconds instead of after a heartbeat timeout.

**Simulation only.** `TradingMode.LIVE` refuses to build a node (ADR-001), so
this process cannot place a real order however it is configured. Running it is how
the runtime meets a real feed for the first time -- a websocket that reconnects,
a venue that rate-limits, a market that goes quiet -- which is the class of
problem a stub cannot produce and a soak run finds in a day.

**Venue reconciliation is built but not constructed here.** `engine.live.readers`
now implements both sides -- what Nautilus's cache holds, and what Binance says
the account holds -- but building the venue reader needs an authenticated HTTP
client, which needs a key, which ADR-001 still forbids. Simulation has no venue
state to disagree with and does not reconcile; live is gated. So the runner is
constructed without readers, and refuses to start a live account for that
reason, which is the correct behaviour until the day a key exists.

When it does: build a `BinanceSpotVenueReader` and a `NautilusCacheReader` here
and pass them to `LiveNodeRunner`. That is the whole change.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
from dataclasses import dataclass

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.exceptions import RedisError

from engine.errors import PreflightFailed
from engine.live.credentials import (
    CredentialResolver,
    EnvironmentCredentialResolver,
    SecretsFileResolver,
    assert_usable_in_live,
)
from engine.live.desired_state import LiveStateStore
from engine.live.kill_switch import CompositeKillSwitch, FileKillSwitch, RedisKillSwitch
from engine.live.mandate import MandateStore
from engine.live.node import LiveNodeRunner
from engine.live.supervisor import Supervisor
from engine.logging import configure_logging
from engine.settings import Settings, get_settings

logger = logging.getLogger(__name__)

#: How often the supervisor re-derives what should be running. Every pass is
#: independent, so a missed one costs exactly this and nothing else.
DEFAULT_INTERVAL_SECONDS = 5.0

#: How long a Redis is given to answer PING at boot. Short: this is a liveness
#: question, not a slow query.
PREFLIGHT_TIMEOUT_SECONDS = 5.0


def holder_id() -> str:
    """Who holds a lease: this process, on this machine.

    A bare UUID would say only that *someone* holds the account. When an
    operator is looking at a stranded lease at 3am, the host and pid are the
    difference between "restart that box" and a search.
    """
    return f"{socket.gethostname()}:{os.getpid()}"


@dataclass(slots=True)
class Components:
    """Everything the loop needs, built together so the wiring is one thing."""

    settings: Settings
    redis: Redis
    store: LiveStateStore
    runner: LiveNodeRunner
    supervisor: Supervisor

    async def aclose(self) -> None:
        await self.redis.aclose()


def _credential_resolver(settings: Settings) -> CredentialResolver:
    """Where a live node finds its key.

    A file mounted at runtime by default, checked for its mode before it is
    read. The environment is the repo owner's documented exception, off unless
    switched on, and it announces itself on every start (ADR-001 addendum).
    """
    if settings.live_allow_env_credentials:
        resolver: CredentialResolver = EnvironmentCredentialResolver()
    else:
        resolver = SecretsFileResolver(settings.live_secrets_dir)
    assert_usable_in_live(resolver, allow_environment=settings.live_allow_env_credentials)
    return resolver


def build_components(settings: Settings, *, holder: str | None = None) -> Components:
    """Construct the control plane. No I/O beyond opening a connection pool.

    Separate from `main` so the wiring itself is testable -- in particular that
    the kill switch really is a composite, which is the one piece of this file
    that a mistake would make silently useless.
    """
    redis: Redis = aioredis.from_url(  # type: ignore[no-untyped-call]
        settings.redis_url, decode_responses=True
    )
    store = LiveStateStore.from_settings(settings, redis)
    runner = LiveNodeRunner(
        settings,
        store,
        mandates=MandateStore(redis),
        resolver=_credential_resolver(settings),
        kill_switch=CompositeKillSwitch(
            RedisKillSwitch(redis),
            # The path that survives Redis being down, the API being wedged, or
            # a partition. An operator with a shell can always stop an account.
            FileKillSwitch(settings.live_kill_switch_dir),
        ),
    )
    supervisor = Supervisor.from_settings(
        settings, store, runner, holder=holder or holder_id()
    )
    return Components(settings, redis, store, runner, supervisor)


async def preflight(settings: Settings) -> None:
    """Both Redis instances must answer before any node is built.

    Not defensive tidiness. `TradingNode(config)` blocks **indefinitely** when
    its cache Redis is unreachable, and does not die on SIGTERM
    (docs/nautilus-api-notes.md D16) -- so a supervisor that discovered this by
    trying would hang its whole reconciliation loop, for every account, with no
    way out but SIGKILL. Failing at boot with a legible message is the
    difference between a deploy that fails and a deploy that wedges.

    The queue Redis is checked in the same pass because the control plane cannot
    read a desired state without it, and two clear errors beat one and a
    surprise.
    """
    if not settings.cache_redis_url:
        raise PreflightFailed(
            "live trading requires NT_CACHE_REDIS_URL; without it a restart "
            "loses every open order and position"
        )

    for name, url in (("queue", settings.redis_url), ("cache", settings.cache_redis_url)):
        client: Redis = aioredis.from_url(url, decode_responses=True)  # type: ignore[no-untyped-call]
        try:
            await asyncio.wait_for(client.ping(), timeout=PREFLIGHT_TIMEOUT_SECONDS)
        except (TimeoutError, OSError, RedisError) as exc:
            raise PreflightFailed(
                f"the {name} Redis at {url} did not answer; "
                "the control plane will not start without it",
                details={"redis": name, "url": url, "error": str(exc)[:200]},
            ) from exc
        finally:
            await client.aclose()
        logger.info("redis reachable", extra={"redis": name})


async def run(
    components: Components, *, interval_seconds: float = DEFAULT_INTERVAL_SECONDS
) -> None:
    """Reconcile until cancelled, then hand the accounts back.

    The `finally` is the whole point of the shutdown path: on a deploy the
    accounts should be picked up by the next supervisor on its next pass, not
    after a heartbeat timeout. A crash cannot run it -- which is exactly why
    the timeout exists as well.
    """
    logger.info(
        "live control plane started",
        extra={
            "holder": components.supervisor.holder,
            "interval_s": interval_seconds,
            "kill_switch_dir": components.settings.live_kill_switch_dir,
        },
    )
    try:
        await components.supervisor.run_forever(interval_seconds=interval_seconds)
    except asyncio.CancelledError:
        logger.info("live control plane stopping")
        raise
    finally:
        await components.supervisor.shutdown()
        # Belt and braces: shutdown() stops what the supervisor started, and
        # this catches a child it does not know about -- one adopted after a
        # restart, or started and then dropped by a failed pass. A live node
        # outliving its control plane is the one outcome worth two calls.
        await components.runner.stop_all()
        await components.aclose()
        logger.info("live control plane stopped")


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    await preflight(settings)
    components = build_components(settings)

    loop = asyncio.get_running_loop()
    task = asyncio.create_task(run(components))
    for received in (signal.SIGINT, signal.SIGTERM):
        # A deploy sends SIGTERM. Cancelling the task rather than exiting the
        # process is what gets the accounts released instead of stranded.
        loop.add_signal_handler(received, task.cancel)

    with contextlib.suppress(asyncio.CancelledError):
        # Cancelling is the ordinary way out, not a failure.
        await task


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
