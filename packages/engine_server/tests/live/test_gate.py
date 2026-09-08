"""The gate: a synchronous answer on the order path, refreshed out of band.

The interesting cases are all about the snapshot going wrong -- never taken,
taken too long ago, or taken from a switch that raised.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from engine.live.gate import DEFAULT_MAX_AGE_NS, NoGate, RiskGate
from engine.live.kill_switch import NeverEngaged
from engine.live.risk import AccountRisk, Breach, OrderIntent, RiskLimits

SECOND = 1_000_000_000

BUY = OrderIntent(instrument_id="BTCUSDT.BINANCE", notional=Decimal(1_000))
CLOSE = OrderIntent(instrument_id="BTCUSDT.BINANCE", notional=Decimal(1_000), reduce_only=True)
FLAT = AccountRisk()


class Engaged:
    async def is_engaged(self, account_id: str) -> bool:
        return True


class Broken:
    async def is_engaged(self, account_id: str) -> bool:
        raise ConnectionError("redis is gone")


def fresh(now_ns: int = 1_000 * SECOND, **kwargs: object) -> RiskGate:
    gate = RiskGate(account_id="acct_1", **kwargs)  # type: ignore[arg-type]
    gate.last_refresh_ns = now_ns
    return gate


# --- staleness -----------------------------------------------------------


def test_a_gate_that_has_never_refreshed_blocks_entries() -> None:
    # A gate that has never spoken to its kill switch is not a gate. This is
    # also the state a freshly constructed live node is in, so the window
    # between "node started" and "first refresh" is closed rather than open.
    gate = RiskGate(account_id="acct_1")

    decision = gate.check(BUY, FLAT, now_ns=0)

    assert not decision.allowed
    assert decision.breach is Breach.KILL_SWITCH


def test_a_stale_gate_blocks_entries() -> None:
    gate = fresh(now_ns=1_000 * SECOND)

    later = 1_000 * SECOND + DEFAULT_MAX_AGE_NS + 1
    assert not gate.check(BUY, FLAT, now_ns=later).allowed


def test_a_gate_inside_its_window_allows() -> None:
    gate = fresh(now_ns=1_000 * SECOND)

    later = 1_000 * SECOND + DEFAULT_MAX_AGE_NS
    assert gate.check(BUY, FLAT, now_ns=later).allowed


def test_a_stale_gate_still_allows_a_close() -> None:
    """The property that makes staleness safe rather than merely strict.

    An account whose gate has gone stale stops opening risk and keeps every
    means of shedding it. The opposite -- trapping a position because the
    supervisor stopped ticking -- would make the safety bound dangerous.
    """
    gate = RiskGate(account_id="acct_1")

    assert gate.check(CLOSE, FLAT, now_ns=0).allowed


# --- refresh -------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_records_the_switch_and_the_time() -> None:
    gate = RiskGate(account_id="acct_1")

    await gate.refresh(NeverEngaged(), now_ns=500 * SECOND)

    assert gate.kill_engaged is False
    assert gate.last_refresh_ns == 500 * SECOND
    assert gate.check(BUY, FLAT, now_ns=500 * SECOND).allowed


@pytest.mark.asyncio
async def test_an_engaged_switch_blocks_the_next_entry() -> None:
    gate = RiskGate(account_id="acct_1")

    await gate.refresh(Engaged(), now_ns=500 * SECOND)

    decision = gate.check(BUY, FLAT, now_ns=500 * SECOND)
    assert decision.breach is Breach.KILL_SWITCH


@pytest.mark.asyncio
async def test_a_switch_that_raises_is_treated_as_engaged() -> None:
    gate = RiskGate(account_id="acct_1")

    await gate.refresh(Broken(), now_ns=500 * SECOND)

    assert gate.kill_engaged is True
    assert not gate.check(BUY, FLAT, now_ns=500 * SECOND).allowed


@pytest.mark.asyncio
async def test_a_release_is_picked_up_by_the_next_refresh() -> None:
    gate = RiskGate(account_id="acct_1")
    await gate.refresh(Engaged(), now_ns=500 * SECOND)

    await gate.refresh(NeverEngaged(), now_ns=501 * SECOND)

    assert gate.check(BUY, FLAT, now_ns=501 * SECOND).allowed


# --- limits reach the gate ----------------------------------------------


@pytest.mark.asyncio
async def test_the_gate_applies_its_limits() -> None:
    gate = RiskGate(
        account_id="acct_1", limits=RiskLimits(max_order_notional=Decimal(500))
    )
    await gate.refresh(NeverEngaged(), now_ns=500 * SECOND)

    decision = gate.check(BUY, FLAT, now_ns=500 * SECOND)

    assert decision.breach is Breach.MAX_ORDER_NOTIONAL


# --- the backtest gate ---------------------------------------------------


def test_the_null_gate_allows_everything() -> None:
    # Backtests have no operator and no account-level limits. Making the gate a
    # null object rather than an optional keeps one order path.
    gate = NoGate()

    assert gate.check(BUY, AccountRisk(open_positions=99), now_ns=0).allowed


# --- a revoked mandate ---------------------------------------------------


class Revoked:
    is_active = False

    def to_limits(self) -> RiskLimits:
        return RiskLimits()


class Active:
    is_active = True

    def __init__(self, limits: RiskLimits) -> None:
        self._limits = limits

    def to_limits(self) -> RiskLimits:
        return self._limits


def test_a_revoked_mandate_blocks_new_entries() -> None:
    gate = fresh()

    gate.apply(Revoked())

    decision = gate.check(BUY, FLAT, now_ns=1_000 * SECOND)
    assert not decision.allowed
    assert decision.breach is Breach.MANDATE_REVOKED


def test_a_revoked_mandate_still_lets_a_position_close() -> None:
    """The difference between withdrawing authority and stopping a process.

    Revocation says "you may not take on more risk"; it does not trap the
    account in what it already holds. The kill switch is the instrument that
    blocks exits too, deliberately, and it is a different endpoint.
    """
    gate = fresh()
    gate.apply(Revoked())

    assert gate.check(CLOSE, FLAT, now_ns=1_000 * SECOND).allowed


def test_an_active_mandate_supplies_the_limits() -> None:
    # One source once a mandate exists: two copies that can disagree is how an
    # account trades inside a limit nobody set (ADR-002).
    gate = fresh(limits=RiskLimits(max_order_notional=Decimal(1)))

    gate.apply(Active(RiskLimits(max_order_notional=Decimal(10_000))))

    assert gate.check(BUY, FLAT, now_ns=1_000 * SECOND).allowed


def test_no_mandate_leaves_the_gate_alone() -> None:
    """Ordinary for a simulation, which risks no money and needs no authority.

    A live node never reaches here with `None` -- it refused to start.
    """
    gate = fresh(limits=RiskLimits(max_order_notional=Decimal(10_000)))

    gate.apply(None)

    assert not gate.mandate_revoked
    assert gate.check(BUY, FLAT, now_ns=1_000 * SECOND).allowed


def test_a_re_grant_lifts_the_block() -> None:
    gate = fresh()
    gate.apply(Revoked())

    gate.apply(Active(RiskLimits()))

    assert gate.check(BUY, FLAT, now_ns=1_000 * SECOND).allowed


def test_the_kill_switch_still_wins_over_everything() -> None:
    # Checked first and alone. A revoked mandate does not soften it into
    # something that permits exits.
    gate = fresh(kill_engaged=True)
    gate.apply(Active(RiskLimits()))

    assert not gate.check(CLOSE, FLAT, now_ns=1_000 * SECOND).allowed
