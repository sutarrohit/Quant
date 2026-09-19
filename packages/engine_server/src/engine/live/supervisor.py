"""The loop that makes the desire true (spec section 10.1).

The API records what an account *should* be doing. This reads that, looks at
what it *is* doing, and closes the gap. It is a reconciliation loop, not a
command processor: a pass that fails changes nothing except that the next pass
tries again.

Four gaps, and what closes each:

===============================  ==========================================
Gap                              Action
===============================  ==========================================
wanted running, nothing running  start
wanted stopped, still running    stop
running an older revision        restart, so a spec change takes effect
running but not heartbeating     restart, because a node holding a position
                                 with nobody managing its stop is the worst
                                 state the system can be in
===============================  ==========================================

**One node per account, enforced by a lease.** An account is the unit of risk,
credentials and reconciliation. Two nodes trading it would each believe they
held the whole position, and the venue would agree with neither.

The thing being supervised is a ``NodeRunner``, which is a protocol. The
Nautilus ``TradingNode`` implementation arrives in the next step; the loop is
built and tested against a runner that records what it was asked to do, because
the logic worth testing is the reconciliation and not the engine.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from engine.errors import ReconciliationFailed
from engine.live.desired_state import (
    DesiredState,
    DesiredStatus,
    LiveStateStore,
    ObservedState,
    ObservedStatus,
)
from engine.logging import log_context
from engine.settings import Settings

logger = logging.getLogger(__name__)


class NodeRunner(Protocol):
    """Whatever actually runs a strategy for an account."""

    async def start(self, state: DesiredState) -> None:
        """Bring an account up. Must be safe to call when it is already up."""
        ...

    async def stop(self, account_id: str) -> None:
        """Bring an account down. Must be safe to call when it is already down."""
        ...

    async def is_running(self, account_id: str) -> bool: ...


@dataclass(slots=True)
class Backoff:
    """How long to wait before starting one account again.

    Kept per account and in memory. A supervisor restart clears it, which is
    the right trade: the new process has no evidence the account is still
    broken, and one immediate attempt is cheaper than an account left waiting
    out a delay nobody can see.
    """

    failures: int = 0
    #: When the account may next be started. `None` means now.
    next_attempt: datetime | None = None
    #: When the current node started, so a start can be judged after the fact.
    started_at: datetime | None = None

    def delay_seconds(self, base: float, ceiling: float) -> float:
        """Exponential, capped. One failure waits `base`, two wait twice that."""
        if self.failures <= 0:
            return 0.0
        return float(min(base * (2 ** (self.failures - 1)), ceiling))


@dataclass(frozen=True, slots=True)
class Action:
    """What a pass decided, and why. Returned so a pass is assertable."""

    account_id: str
    action: str
    reason: str


class Supervisor:
    def __init__(
        self,
        store: LiveStateStore,
        runner: NodeRunner,
        *,
        holder: str,
        heartbeat_timeout_seconds: int = 90,
        restart_backoff_seconds: float = 5.0,
        restart_backoff_max_seconds: float = 300.0,
        healthy_after_seconds: float = 60.0,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._runner = runner
        self._holder = holder
        self._timeout = heartbeat_timeout_seconds
        self._backoff_base = restart_backoff_seconds
        self._backoff_max = restart_backoff_max_seconds
        self._healthy_after = healthy_after_seconds
        self._backoff: dict[str, Backoff] = {}
        self._now = now
        #: Accounts this supervisor started, so shutdown can hand back exactly
        #: what it holds and nothing else.
        self._held: set[str] = set()

    @property
    def holder(self) -> str:
        """Who this supervisor is, as written into a lease."""
        return self._holder

    @classmethod
    def from_settings(
        cls, settings: Settings, store: LiveStateStore, runner: NodeRunner, *, holder: str
    ) -> Supervisor:
        return cls(
            store,
            runner,
            holder=holder,
            heartbeat_timeout_seconds=settings.live_heartbeat_timeout_seconds,
            restart_backoff_seconds=settings.live_restart_backoff_seconds,
            restart_backoff_max_seconds=settings.live_restart_backoff_max_seconds,
            healthy_after_seconds=settings.live_healthy_after_seconds,
        )

    async def reconcile_once(self) -> list[Action]:
        """One pass over every account. Returns what it did.

        **One account's problem never becomes every account's.** A record that
        cannot even be read -- written by an older version, corrupted, hand-
        edited -- would otherwise raise out of this loop and stall the pass, so
        every *other* account goes untended for as long as the bad one exists.
        That is the same shape as the crash loop: a local failure with a global
        blast radius.

        So each account is isolated. A failure is logged and skipped, and the
        account is left exactly as it is -- in particular a running node is not
        stopped because its record became unreadable. The node is the thing
        holding the position; the record is a description of it.
        """
        actions: list[Action] = []
        for account_id in await self._store.accounts():
            try:
                action = await self._reconcile_account(account_id)
            except Exception:
                logger.exception(
                    "could not reconcile an account; leaving it as it is",
                    extra={"account_id": account_id},
                )
                continue
            if action is not None:
                actions.append(action)
        return actions

    async def _reconcile_account(self, account_id: str) -> Action | None:
        desired = await self._store.get(account_id)
        if desired is None:
            return None

        with log_context(account_id=account_id):
            observed = await self._store.observed(account_id)

            if desired.status is DesiredStatus.STOPPED:
                if observed is not None and observed.status is not ObservedStatus.STOPPED:
                    # Any state but STOPPED, not only a live one. A halted or
                    # failed account that an operator asks to stop must reach
                    # STOPPED as well, or the two records never converge and
                    # the loop stops being a reconciliation: the operator sees
                    # HALTED forever and has no way to say "I am done with it".
                    # `runner.stop` is idempotent, so stopping something that
                    # was never started costs nothing.
                    return await self._stop(desired, "operator asked for it to stop")
                return None

            if observed is not None and observed.status.needs_operator:
                if observed.revision == desired.revision:
                    # Halted on this exact revision. Restarting would repeat
                    # the disagreement; an operator re-states the desire to
                    # clear it, which bumps the revision.
                    logger.debug("account is halted and awaiting an operator")
                    return None
                logger.info("halt cleared by a new revision")

            if not await self._store.acquire(account_id, self._holder):
                # Another supervisor holds this account. Leaving it alone is
                # the whole point of the lease.
                logger.debug("account is held elsewhere")
                return None

            if observed is None or not observed.status.is_live:
                if observed is not None and observed.revision != desired.revision:
                    # An operator restated the desired state after the failure.
                    # That is a new thing to try rather than a retry of the old
                    # one, and it does not wait out a delay earned by a spec
                    # that has since been replaced. (A FAILED account never
                    # reaches the revision check below, which is why the rule
                    # is repeated here rather than only there.)
                    self._backoff.pop(account_id, None)
                self._judge_previous_start(account_id)
                if not self._may_start(account_id):
                    return None
                return await self._start(desired, "nothing was running")

            if observed.revision != desired.revision:
                # An operator changed the spec. That is a new thing to try, not
                # a retry of the old one, so it clears the backoff rather than
                # waiting it out -- restating the desired state is the same
                # gesture that clears a halt.
                self._backoff.pop(account_id, None)
                return await self._restart(
                    desired, f"running revision {observed.revision}, wanted {desired.revision}"
                )

            if observed.is_stale(now=self._now(), timeout_seconds=self._timeout):
                # Judged like any other start: a node that heartbeated for an
                # hour and then wedged has earned a clean slate, and one that
                # wedges immediately every time has not.
                self._judge_previous_start(account_id)
                if not self._may_start(account_id):
                    return None
                return await self._restart(desired, "the node stopped heartbeating")

            if not await self._runner.is_running(account_id):
                # The record says running and the runner disagrees. Trust the
                # runner: it is closer to the truth. This is the crash-loop
                # path -- a child that dies at startup lands here every pass --
                # so it is the one that must respect the backoff.
                self._judge_previous_start(account_id)
                if not self._may_start(account_id):
                    return None
                return await self._restart(desired, "the record disagreed with the runner")

            return None

    # --- actions ---------------------------------------------------------

    async def _start(self, desired: DesiredState, reason: str) -> Action:
        await self._store.observe(
            ObservedState(
                account_id=desired.account_id,
                status=ObservedStatus.STARTING,
                revision=desired.revision,
                started_at=self._now(),
                heartbeat_at=self._now(),
            )
        )
        try:
            await self._runner.start(desired)
        except ReconciliationFailed as exc:
            # Not a crash. The node and the venue disagree about money, and
            # retrying cannot resolve that (spec section 10.3).
            logger.error("halted: the node disagrees with the venue", extra={"reason": reason})
            await self._store.observe(
                ObservedState(
                    account_id=desired.account_id,
                    status=ObservedStatus.HALTED,
                    revision=desired.revision,
                    error={"code": exc.code.value, "message": exc.message, **(exc.details or {})},
                    heartbeat_at=self._now(),
                )
            )
            return Action(desired.account_id, "halted", "reconciliation failed")
        except Exception as exc:
            logger.exception("could not start the node", extra={"reason": reason})
            await self._store.observe(
                ObservedState(
                    account_id=desired.account_id,
                    status=ObservedStatus.FAILED,
                    revision=desired.revision,
                    error={"code": type(exc).__name__, "message": str(exc)[:200]},
                    heartbeat_at=self._now(),
                )
            )
            # Not re-raised: one account failing to start must not stop the
            # loop from tending the others.
            self._record_failure(desired.account_id, "the node could not be started")
            return Action(desired.account_id, "start_failed", reason)

        await self._store.observe(
            ObservedState(
                account_id=desired.account_id,
                status=ObservedStatus.RUNNING,
                revision=desired.revision,
                started_at=self._now(),
                heartbeat_at=self._now(),
            )
        )
        self._held.add(desired.account_id)
        self._backoff.setdefault(desired.account_id, Backoff()).started_at = self._now()
        logger.info("node started", extra={"reason": reason, "revision": desired.revision})
        return Action(desired.account_id, "start", reason)

    # --- backoff ---------------------------------------------------------

    def _may_start(self, account_id: str) -> bool:
        state = self._backoff.get(account_id)
        if state is None or state.next_attempt is None:
            return True
        if self._now() >= state.next_attempt:
            return True
        logger.info(
            "start deferred by backoff",
            extra={
                "account_id": account_id,
                "failures": state.failures,
                "next_attempt": state.next_attempt.isoformat(),
            },
        )
        return False

    def _judge_previous_start(self, account_id: str) -> None:
        """Decide, after the fact, whether the last start actually worked.

        A node that came up and died in ten seconds has not started, whatever
        the process table said in between -- and it is the failure that loops,
        because every pass finds nothing running and tries again. Surviving
        `healthy_after_seconds` is what clears the count.
        """
        state = self._backoff.get(account_id)
        if state is None or state.started_at is None:
            return
        lived = (self._now() - state.started_at).total_seconds()
        state.started_at = None
        if lived >= self._healthy_after:
            if state.failures:
                logger.info(
                    "backoff cleared: the node ran long enough to count",
                    extra={"account_id": account_id, "ran_seconds": lived},
                )
            state.failures = 0
            state.next_attempt = None
            return
        self._record_failure(account_id, f"the node lived {lived:.0f}s")

    def _record_failure(self, account_id: str, why: str) -> None:
        state = self._backoff.setdefault(account_id, Backoff())
        state.failures += 1
        state.started_at = None
        delay = state.delay_seconds(self._backoff_base, self._backoff_max)
        state.next_attempt = self._now() + timedelta(seconds=delay)
        logger.warning(
            "start failed; backing off",
            extra={
                "account_id": account_id,
                "failures": state.failures,
                "delay_seconds": delay,
                "reason": why,
            },
        )

    async def _stop(self, desired: DesiredState, reason: str) -> Action:
        try:
            await self._runner.stop(desired.account_id)
        finally:
            await self._store.observe(
                ObservedState(
                    account_id=desired.account_id,
                    status=ObservedStatus.STOPPED,
                    revision=desired.revision,
                    heartbeat_at=self._now(),
                )
            )
            await self._store.release(desired.account_id, self._holder)
            self._held.discard(desired.account_id)
            # An operator asking for a stop is not a failed start.
            self._backoff.pop(desired.account_id, None)
        logger.info("node stopped", extra={"reason": reason})
        return Action(desired.account_id, "stop", reason)

    async def _restart(self, desired: DesiredState, reason: str) -> Action:
        logger.info("restarting node", extra={"reason": reason})
        try:
            await self._runner.stop(desired.account_id)
        except Exception:
            # A node that cannot be stopped cleanly is still one this pass has
            # to replace; the failure is logged and the start attempted.
            logger.exception("stopping before restart failed")
        started = await self._start(desired, reason)
        return Action(desired.account_id, "restart", started.reason)

    # --- the loop --------------------------------------------------------

    async def shutdown(self) -> None:
        """Hand back every account this supervisor is running.

        A deploy is not a crash, and should not be treated as one. Stopping the
        nodes and releasing the leases lets the next supervisor pick the
        accounts up on its next pass -- seconds -- instead of waiting out a
        heartbeat timeout with nobody managing a stop.

        The observed record is set to STOPPED because that is now true. It also
        means recovery does not have to wait for the heartbeat to go stale to
        notice, since a status that is not live is reason enough to start.

        Nothing here can be relied on: a `kill -9` runs none of it. That is what
        the heartbeat timeout is for, and why this is an optimisation rather
        than a mechanism.
        """
        for account_id in sorted(self._held):
            with log_context(account_id=account_id):
                try:
                    await self._runner.stop(account_id)
                except Exception:
                    # One account refusing to stop must not strand the others.
                    logger.exception("could not stop a node during shutdown")
                observed = await self._store.observed(account_id)
                if observed is not None:
                    await self._store.observe(
                        observed.model_copy(
                            update={
                                "status": ObservedStatus.STOPPED,
                                "heartbeat_at": self._now(),
                            }
                        )
                    )
                await self._store.release(account_id, self._holder)
        released = sorted(self._held)
        self._held.clear()
        logger.info("supervisor shut down", extra={"released": released})

    async def run_forever(self, *, interval_seconds: float = 5.0) -> None:  # pragma: no cover
        """Reconcile until cancelled.

        Every pass is independent and re-derives what to do from the records,
        so a missed pass, a crash, or a restart costs one interval and nothing
        else.
        """
        logger.info("supervisor started", extra={"holder": self._holder})
        while True:
            try:
                await self.reconcile_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("reconciliation pass failed")
            await asyncio.sleep(interval_seconds)
