from __future__ import annotations

import copy
import os
import time
from decimal import Decimal
from typing import Any

import pytest

from engine.backtest.runner import RunOutcome, execute, run_isolated
from engine.errors import BacktestFailed, BacktestIncomplete, BacktestTimeout, NoDataForWindow
from engine.settings import Settings
from engine.types.backtest import BacktestRequest
from tests.worker.conftest import requires_catalog


def _die_immediately(*args: object, **kwargs: object) -> None:
    """Exit without touching the outbox, the way a crash does."""
    os._exit(1)


pytestmark = requires_catalog


@pytest.fixture
def request_model(submission: dict[str, Any]) -> BacktestRequest:
    return BacktestRequest.model_validate(submission)


# --- running -------------------------------------------------------------


def test_a_backtest_runs_in_process(
    request_model: BacktestRequest, worker_settings: Settings
) -> None:
    outcome = execute(request_model, worker_settings)

    assert isinstance(outcome, RunOutcome)
    assert outcome.fills > 0
    assert outcome.closed_positions > 0
    assert outcome.total_commission > 0
    assert isinstance(outcome.realized_pnl, Decimal)


def test_a_backtest_runs_in_a_child_process(
    request_model: BacktestRequest, worker_settings: Settings
) -> None:
    result = run_isolated(request_model, worker_settings)

    assert result["fills"] > 0
    assert result["closedPositions"] > 0
    # Money crosses as strings, so the parent never reconstructs it as a float.
    assert isinstance(result["realizedPnl"], str)
    assert isinstance(result["totalCommission"], str)


def test_isolation_produces_the_same_answer_as_in_process(
    request_model: BacktestRequest, worker_settings: Settings
) -> None:
    # A child process must not change the answer; if it did, something is
    # reaching the run through the environment rather than the inputs.
    direct = execute(request_model, worker_settings)
    isolated = run_isolated(request_model, worker_settings)
    assert isolated == direct.to_payload()


def test_repeated_runs_agree(
    request_model: BacktestRequest, worker_settings: Settings
) -> None:
    # A fresh process per run must not change the answer; if it did, something
    # is leaking through the environment rather than the inputs.
    assert run_isolated(request_model, worker_settings) == run_isolated(
        request_model, worker_settings
    )


def test_costs_reach_the_run(
    submission: dict[str, Any], worker_settings: Settings
) -> None:
    free = copy.deepcopy(submission)
    free["fees"] = {"makerBps": "0", "takerBps": "0"}
    free["slippageBps"] = "0"

    charged_result = run_isolated(BacktestRequest.model_validate(submission), worker_settings)
    free_result = run_isolated(BacktestRequest.model_validate(free), worker_settings)

    assert Decimal(free_result["totalCommission"]) == 0
    assert Decimal(charged_result["totalCommission"]) > 0
    assert Decimal(charged_result["realizedPnl"]) < Decimal(free_result["realizedPnl"])


# --- the timeout ---------------------------------------------------------


def test_a_run_that_exceeds_its_ceiling_is_killed(
    request_model: BacktestRequest, worker_settings: Settings
) -> None:
    """Spec section 7.4.

    A backtest is a CPU-bound Rust loop that never checks for cancellation, so
    the ceiling is enforced by terminating the process. Half a second is below
    the cost of spawning and importing Nautilus, so this fires reliably rather
    than depending on how fast the machine runs a backtest.
    """
    with pytest.raises(BacktestTimeout, match="exceeded 0.5s|exceeded 0s"):
        run_isolated(request_model, worker_settings, timeout_seconds=0.5)  # type: ignore[arg-type]


def test_a_timeout_leaves_no_process_behind(
    request_model: BacktestRequest, worker_settings: Settings
) -> None:
    # A killed run must actually be gone; otherwise a worker accumulates
    # orphaned backtests until the box runs out of memory.
    import multiprocessing

    before = len(multiprocessing.active_children())
    with pytest.raises(BacktestTimeout):
        run_isolated(request_model, worker_settings, timeout_seconds=0.5)  # type: ignore[arg-type]
    assert len(multiprocessing.active_children()) <= before


# --- misconfiguration is not a zero-trade result -------------------------


def test_an_unknown_bar_type_is_refused(
    submission: dict[str, Any], worker_settings: Settings
) -> None:
    """Nautilus does not fail on this, and that is the problem.

    A missing instrument makes the strategy's ``on_start`` raise; Nautilus logs
    the error, carries on, and the run returns a perfectly successful result
    with zero fills -- indistinguishable from a strategy that genuinely found
    no signals. Checked up front instead.
    """
    submission["instrumentId"] = "NOTREAL.BINANCE"
    submission["barType"] = "NOTREAL.BINANCE-15-MINUTE-LAST-EXTERNAL"

    with pytest.raises(NoDataForWindow, match="holds no bars"):
        run_isolated(BacktestRequest.model_validate(submission), worker_settings)


def test_a_window_outside_the_data_is_refused(
    submission: dict[str, Any], worker_settings: Settings
) -> None:
    submission["start"] = "2019-01-01T00:00:00Z"
    submission["end"] = "2019-02-01T00:00:00Z"

    with pytest.raises(NoDataForWindow, match="does not overlap"):
        run_isolated(BacktestRequest.model_validate(submission), worker_settings)


def test_the_check_runs_before_a_process_is_spawned(
    submission: dict[str, Any], worker_settings: Settings
) -> None:
    # Spawning a process to discover the catalog is empty costs seconds and
    # returns a worse error.
    import time

    submission["instrumentId"] = "NOTREAL.BINANCE"
    submission["barType"] = "NOTREAL.BINANCE-15-MINUTE-LAST-EXTERNAL"

    started = time.perf_counter()
    with pytest.raises(NoDataForWindow):
        run_isolated(BacktestRequest.model_validate(submission), worker_settings)
    assert time.perf_counter() - started < 1.0


def test_a_valid_window_at_the_edge_of_the_data_is_allowed(
    submission: dict[str, Any], worker_settings: Settings
) -> None:
    submission["start"] = "2023-01-01T00:00:00Z"
    submission["end"] = "2023-01-08T00:00:00Z"
    assert run_isolated(BacktestRequest.model_validate(submission), worker_settings)["fills"] >= 0


# --- a child that dies without reporting ---------------------------------


def test_a_child_that_dies_silently_does_not_hang_the_parent(
    request_model: BacktestRequest, worker_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crashed child must not cost the full timeout.

    Killed by the OOM killer, or dead in a native extension, it puts nothing on
    the queue. Blocking on a single long ``get`` would leave the parent waiting
    out the entire ceiling for an answer that is never coming.
    """
    import engine.backtest.runner as runner_module

    monkeypatch.setattr(runner_module, "_child", _die_immediately)

    started = time.perf_counter()
    with pytest.raises(BacktestFailed, match="exited without a result"):
        run_isolated(request_model, worker_settings, timeout_seconds=60)
    assert time.perf_counter() - started < 20, "the parent waited out the timeout"


# --- a halted run is not a successful one --------------------------------


def test_a_truncated_run_is_reported_not_returned(
    submission: dict[str, Any], worker_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nautilus halts on conditions like a negative balance, and `run()` then
    returns normally. The reports describe only the part that ran, and look
    exactly like an ordinary short result.

    The strategy is told its costs are zero, so it sizes a position it cannot
    pay the fee on -- which is the real bug this check was written for.
    """
    import engine.backtest.runner as runner_module
    from engine.backtest.builder import build_run_config

    def understate_costs(request: Any, spec: Any, settings: Any) -> Any:
        config = build_run_config(request, spec, settings)
        config.engine.strategies[0].config["cost_bps"] = "0"
        return config

    # A spec that spends essentially the whole balance on each entry.
    submission["spec"]["sizing"] = {"type": "riskPercent", "riskPercent": "99"}
    submission["spec"]["exit"] = {"any": [{"type": "stopLossPercent", "value": "99"}]}
    submission["fees"] = {"makerBps": "50", "takerBps": "50"}
    submission["slippageBps"] = "50"
    monkeypatch.setattr(runner_module, "build_run_config", understate_costs)

    with pytest.raises(BacktestIncomplete, match="halted rather than completed"):
        execute(BacktestRequest.model_validate(submission), worker_settings)


def test_a_complete_run_is_not_flagged(
    request_model: BacktestRequest, worker_settings: Settings
) -> None:
    # The check must not fire on an ordinary result, or it is worse than
    # useless.
    assert execute(request_model, worker_settings).fills >= 0


def test_sizing_leaves_room_for_its_own_commission(
    submission: dict[str, Any], worker_settings: Settings
) -> None:
    # With costs correctly known, a strategy sizing at 99% of equity must still
    # be able to pay the fee and run to completion.
    submission["spec"]["sizing"] = {"type": "riskPercent", "riskPercent": "99"}
    submission["spec"]["exit"] = {"any": [{"type": "stopLossPercent", "value": "99"}]}
    submission["fees"] = {"makerBps": "50", "takerBps": "50"}
    submission["slippageBps"] = "50"

    outcome = execute(BacktestRequest.model_validate(submission), worker_settings)
    assert outcome.fills > 0
