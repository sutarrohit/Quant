"""The risk gate on the real order path.

`tests/live/test_gate.py` covers the gate's own logic. What it cannot show is
that anything consults it -- so these run a real backtest with the gate
replaced and check that orders stop.

The injection point is ``dsl_strategy.NoGate``, the null object the strategy
builds for itself. Nautilus constructs the strategy from a serialisable config,
so a gate cannot be passed in through one; a live node reaches in and sets
``risk_gate`` on the built instance, and patching the default here exercises
exactly the same attribute.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from engine.live.risk import ALLOWED, AccountRisk, Breach, Decision, OrderIntent, Verdict
from tests.strategies.conftest import requires_catalog, run_backtest


def submissions(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if record["message"] == "entry submitted"]


def blocks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if record["message"] == "entry blocked by the risk gate"]


class Blocking:
    """Stands in for an engaged kill switch."""

    def check(self, intent: OrderIntent, account: AccountRisk, now_ns: int) -> Decision:
        return Decision(Verdict.REJECT, "stopped by the operator", Breach.KILL_SWITCH)


class Recording:
    """Allows everything, and remembers what it was asked."""

    def __init__(self) -> None:
        self.seen: list[tuple[OrderIntent, AccountRisk, int]] = []

    def check(self, intent: OrderIntent, account: AccountRisk, now_ns: int) -> Decision:
        self.seen.append((intent, account, now_ns))
        return ALLOWED


@requires_catalog
def test_without_a_gate_a_backtest_submits_orders(rsi_spec: dict[str, Any]) -> None:
    # The baseline the rest of this file is measured against: in a backtest the
    # gate is the null object and nothing is held back.
    records = run_backtest(rsi_spec)

    assert submissions(records)
    assert blocks(records) == []


@requires_catalog
def test_a_blocking_gate_stops_every_entry(
    rsi_spec: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("engine.strategies.dsl_strategy.NoGate", Blocking)

    records = run_backtest(rsi_spec)

    assert blocks(records), "the strategy still had signals to act on"
    assert submissions(records) == []


@requires_catalog
def test_a_block_records_which_limit_stopped_it(
    rsi_spec: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # An operator asking "why is this account not trading" must get an answer
    # from the logs without attaching a debugger.
    monkeypatch.setattr("engine.strategies.dsl_strategy.NoGate", Blocking)

    first = blocks(run_backtest(rsi_spec))[0]

    assert first["breach"] == "KILL_SWITCH"
    assert first["reason"] == "stopped by the operator"
    assert first["spec_hash"]
    assert first["notional"]


@requires_catalog
def test_the_gate_is_asked_about_the_order_it_would_submit(
    rsi_spec: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The notional shown to the gate is the one the venue would receive.

    A limit checked against a different number than the order carries is worse
    than no limit: it reads as protection and is not.
    """
    recording = Recording()
    monkeypatch.setattr("engine.strategies.dsl_strategy.NoGate", lambda: recording)

    records = run_backtest(rsi_spec)

    assert recording.seen
    assert len(recording.seen) == len(submissions(records))
    for (intent, _, _), record in zip(recording.seen, submissions(records), strict=True):
        assert intent.notional == Decimal(record["notional"])
        assert intent.instrument_id == "BTCUSDT.BINANCE"
        # An entry is never reduce-only; the exemption must not apply to it.
        assert intent.reduce_only is False


@requires_catalog
def test_the_gate_sees_the_account_as_flat_before_an_entry(
    rsi_spec: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # v1 is one position at a time, so every entry is decided from flat. The
    # test exists to catch the day that stops being true silently.
    recording = Recording()
    monkeypatch.setattr("engine.strategies.dsl_strategy.NoGate", lambda: recording)

    run_backtest(rsi_spec)

    assert all(account.open_positions == 0 for _, account, _ in recording.seen)
    assert all(account.open_notional == Decimal(0) for _, account, _ in recording.seen)


@requires_catalog
def test_the_gate_reads_the_strategy_clock(
    rsi_spec: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never a wall clock.

    `now_ns` decides staleness, and a gate that read `time.monotonic_ns()` would
    make a backtest non-deterministic and a replay untestable.
    """
    recording = Recording()
    monkeypatch.setattr("engine.strategies.dsl_strategy.NoGate", lambda: recording)

    run_backtest(rsi_spec)

    stamps = [now_ns for _, _, now_ns in recording.seen]
    assert stamps == sorted(stamps)
    submitted = submissions(run_backtest(rsi_spec))
    assert stamps == [record["ts_event"] for record in submitted]


@requires_catalog
def test_a_block_names_the_authority_it_was_refused_under(
    rsi_spec: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-002 condition 5: which limit, which values, **which mandate**.

    Without the mandate id, answering "why did this order not go" means
    joining two services' records on a timestamp — at exactly the moment
    nobody wants to be doing that.
    """

    class WithMandate(Blocking):
        mandate_id = "m_soak_1"

    monkeypatch.setattr("engine.strategies.dsl_strategy.NoGate", WithMandate)

    first = blocks(run_backtest(rsi_spec))[0]

    assert first["mandate_id"] == "m_soak_1"


@requires_catalog
def test_a_block_without_a_mandate_says_so_rather_than_omitting_it(
    rsi_spec: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A simulation has no mandate. An absent key and a null are different
    # things to a log query, and the second is the honest one.
    monkeypatch.setattr("engine.strategies.dsl_strategy.NoGate", Blocking)

    first = blocks(run_backtest(rsi_spec))[0]

    assert "mandate_id" in first
    assert first["mandate_id"] is None
