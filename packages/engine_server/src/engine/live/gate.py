"""The risk gate as the order path actually sees it: synchronously.

The decision happens in `Strategy.on_bar`, which Nautilus calls **synchronously**
on the loop carrying the venue's websocket -- so awaiting Redis there would stall
order handling and fill reports.

The gate therefore holds a *snapshot* of the limits and the kill switch,
refreshed out of band by the supervisor and read without blocking.

**A stale snapshot counts as engaged.** If refreshes stopped, the gate does not
know what the operator has said since. `max_age` is a safety bound, not a cache
TTL. Exits are never gated, so a stale gate stops new risk and keeps every means
of shedding it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from engine.live.kill_switch import KillSwitch
from engine.types.risk import AccountRisk, Breach, Decision, OrderIntent, RiskLimits, Verdict

logger = logging.getLogger(__name__)

#: How old a snapshot may be before the gate stops trusting it. Generous
#: against the supervisor's own interval, so an ordinary slow tick does not
#: halt trading, and short against how long an operator would accept a node
#: ignoring a kill.
DEFAULT_MAX_AGE_NS = 30 * 1_000_000_000


@dataclass(slots=True)
class RiskGate:
    """What the strategy consults before submitting an entry.

    ``last_refresh_ns`` is Unix-epoch nanoseconds, the same clock as ``now_ns``
    passed to :meth:`check` — the strategy's Nautilus clock in live, so the gate
    never reads a clock of its own and stays deterministic. Not monotonic: the
    two would differ by decades and every entry would read as stale.
    """

    account_id: str
    limits: RiskLimits = field(default_factory=RiskLimits)
    kill_engaged: bool = False
    #: Withdrawn authority (ADR-002). Blocks new entries and permits exits,
    #: like every other brake except the kill switch -- flattening on revoke
    #: would let a control-plane event decide a trade.
    mandate_revoked: bool = False
    #: Which grant of authority this account is trading under. On every block,
    #: so "why did this order not go" is answerable from one log line rather
    #: than by joining two services' records (ADR-002 condition 5).
    mandate_id: str | None = None
    last_refresh_ns: int | None = None
    max_age_ns: int = DEFAULT_MAX_AGE_NS

    def check(self, intent: OrderIntent, account: AccountRisk, now_ns: int) -> Decision:
        from engine.live.risk import evaluate

        if self._is_stale(now_ns) and not intent.reduce_only:
            return Decision(
                Verdict.REJECT,
                "the risk gate has not been refreshed recently enough to be trusted",
                Breach.KILL_SWITCH,
            )
        if self.mandate_revoked and not intent.reduce_only:
            return Decision(
                Verdict.REJECT,
                "the mandate for this account has been revoked",
                Breach.MANDATE_REVOKED,
            )
        return evaluate(intent, account, self.limits, kill_engaged=self.kill_engaged)

    def _is_stale(self, now_ns: int) -> bool:
        if self.last_refresh_ns is None:
            # Never refreshed. A gate that has never spoken to its kill switch
            # is not a gate.
            return True
        return now_ns - self.last_refresh_ns > self.max_age_ns

    def apply(self, mandate: object | None) -> None:
        """Take the current mandate's authority and terms.

        `None` means no mandate exists. For a simulation that is ordinary -- it
        risks no money and needs no authority. For live it never happens,
        because the node refused to start.
        """
        if mandate is None:
            return
        self.mandate_revoked = not getattr(mandate, "is_active", True)
        self.mandate_id = getattr(mandate, "mandate_id", None)
        if not self.mandate_revoked:
            # The mandate is the single source of limits once one exists, so
            # the two cannot drift (ADR-002).
            self.limits = mandate.to_limits()  # type: ignore[attr-defined]

    async def refresh(self, switch: KillSwitch, now_ns: int) -> None:
        """Take a fresh snapshot. Called by the supervisor, never on the order path.

        `CompositeKillSwitch` already turns an unreadable path into "engaged",
        so an exception reaching here means the switch object itself failed. The
        snapshot is still stamped: an engaged-and-fresh gate and a stale gate
        both stop new orders, and stamping keeps the reason in the logs honest.
        """
        try:
            self.kill_engaged = await switch.is_engaged(self.account_id)
        except Exception:
            logger.exception(
                "the kill switch could not be read; treating it as engaged",
                extra={"account_id": self.account_id},
            )
            self.kill_engaged = True
        self.last_refresh_ns = now_ns


class NoGate:
    """Allows everything. What a backtest uses.

    Backtests have no operator, no kill switch and no account-level limits —
    they have one account, one strategy and a fixed starting balance. Making
    the gate optional in the strategy would mean a ``None`` check on the order
    path; making it a null object means backtest and live run the same code.
    """

    def check(self, intent: OrderIntent, account: AccountRisk, now_ns: int) -> Decision:
        from engine.types.risk import ALLOWED

        return ALLOWED
