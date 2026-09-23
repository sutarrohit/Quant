"""Executing one backtest (spec section 7.4).

Runs in the worker, never in the API process.

**Each run gets a fresh process**, for three reasons from the spec: a Nautilus
engine leaks memory until the worker OOMs, state must not leak between runs, and
a CPU-bound Rust loop never checks for cancellation, so a timeout means killing
it rather than asking.

The engine is disposed after extraction, not before: ``dispose_on_completion``
defaults to True and clears the cache before ``run()`` returns, which makes
every report come back empty (D9).
"""

from __future__ import annotations

import logging
import multiprocessing
import queue as queue_module
import time
import traceback
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from engine.backtest.builder import build_run_config
from engine.backtest.results import build_equity_curve, build_trades, summarise
from engine.data.catalog import Catalog
from engine.errors import BacktestFailed, BacktestIncomplete, BacktestTimeout, NoDataForWindow
from engine.settings import Settings
from engine.types.backtest import BacktestRequest
from engine.types.dsl import StrategySpec

logger = logging.getLogger(__name__)

# Spawn rather than fork: the child re-imports cleanly instead of inheriting a
# parent that has already loaded Nautilus's Rust extensions and an event loop.
_CONTEXT = multiprocessing.get_context("spawn")

#: How often to check whether the child is still alive.
_POLL_SECONDS = 0.25


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """What one run produced: the counts, the metrics, and the series."""

    fills: int
    positions: int
    closed_positions: int
    realized_pnl: Decimal
    total_commission: Decimal
    summary: dict[str, Any] = field(default_factory=dict)
    trades: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)

    def to_result(self) -> dict[str, Any]:
        """The JSON a caller receives.

        The series are deliberately absent: they are written to Parquet and
        referenced, never inlined (spec section 7.5).
        """
        return {
            "fills": self.fills,
            "positions": self.positions,
            "closedPositions": self.closed_positions,
            "realizedPnl": str(self.realized_pnl),
            "totalCommission": str(self.total_commission),
            "summary": self.summary,
        }

    def to_payload(self) -> dict[str, Any]:
        """Everything, including the series, for crossing the process boundary."""
        return {**self.to_result(), "trades": self.trades, "equityCurve": self.equity_curve}


def _to_ns(moment: Any) -> int:
    return int(moment.timestamp() * 1_000) * 1_000_000


def _assert_complete(engine: Any, expected_bars: int) -> None:
    """Verify the engine consumed every bar it was given.

    The strategy counts them, so the check is exact rather than a heuristic
    about when the last trade happened -- a strategy may legitimately stop
    trading long before the data ends.
    """
    strategies = engine.trader.strategies()
    if not strategies or expected_bars == 0:
        return
    seen = getattr(strategies[0], "bars_seen", None)
    if seen is None:
        return
    if seen < expected_bars:
        raise BacktestIncomplete(
            f"the engine stopped after {seen} of {expected_bars} bars; "
            "the run was halted rather than completed",
            details={"barsSeen": seen, "barsExpected": expected_bars},
        )


def _open_position_value(
    positions: Any,
    engine: Any,
    request: BacktestRequest,
    settings: Settings,
    *,
    price_precision: int | None,
) -> tuple[Decimal, int]:
    """Mark a position still open on the last bar to that bar's close.

    Excluding it understates a trend follower badly: such a strategy is usually
    still holding when the data ends. Measured against backtesting.py, omitting
    it cost 77 percentage points of reported return.
    """
    from engine.data.catalog import Catalog

    if len(positions) == 0 or "avg_px_close" not in positions.columns:
        return Decimal(0), 0

    still_open = positions[positions["avg_px_close"].isna()]
    if len(still_open) == 0:
        return Decimal(0), 0

    bars = Catalog.from_settings(settings).read_bars(
        request.bar_type, start=_to_ns(request.start), end=_to_ns(request.end)
    )
    if not bars:
        return Decimal(0), 0
    last_close = bars[-1].close.as_decimal()

    total = Decimal(0)
    for _, row in still_open.iterrows():
        quantity = Decimal(str(row["peak_qty"]))
        entry = Decimal(str(row["avg_px_open"]))
        if price_precision is not None:
            entry = entry.quantize(Decimal(1).scaleb(-price_precision))
        # Commission already paid on the open leg is a realized cost.
        total += quantity * (last_close - entry) - _sum_money([row.get("commissions", [])])
    return total, len(still_open)


def _price_precision(request: BacktestRequest, settings: Settings) -> int | None:
    """The instrument's tick precision, for quantizing reported prices."""
    from engine.data.catalog import Catalog

    for instrument in Catalog.from_settings(settings).instruments():
        if str(instrument.id) == request.instrument_id:
            precision: int = instrument.price_precision
            return precision
    return None


def _starting_equity(request: BacktestRequest) -> Decimal:
    """The quote-currency balance the run began with.

    ``startingBalances`` are venue strings like ``"10000 USDT"``. The first is
    taken as the account's quote currency, which is what a CASH account on a
    single pair actually trades with.
    """
    for balance in request.starting_balances:
        amount = balance.split()[0]
        return Decimal(amount)
    return Decimal(0)


def _sum_money(cells: Any) -> Decimal:
    """Total a report column of Money values, which may hold lists."""
    total = Decimal(0)
    for cell in cells:
        for item in cell if isinstance(cell, list) else [cell]:
            text = str(item)
            if text and text != "nan" and text != "None":
                total += Decimal(text.split()[0])
    return total


def check_data_available(request: BacktestRequest, settings: Settings) -> None:
    """Refuse to run against data that is not there.

    A zero-trade result is a legitimate outcome, so it cannot also be how a
    misconfigured run reports itself.
    """
    from engine.data.catalog import Catalog

    catalog = Catalog.from_settings(settings)
    if request.bar_type not in catalog.bar_types():
        raise NoDataForWindow(
            f"the catalog holds no bars for {request.bar_type}",
            details={"barType": request.bar_type, "available": catalog.bar_types()},
        )

    coverage = catalog.coverage(request.bar_type)
    if coverage is None or coverage.end <= request.start or coverage.start >= request.end:
        held = f"{coverage.start.isoformat()}..{coverage.end.isoformat()}" if coverage else "nothing"
        raise NoDataForWindow(
            f"{request.bar_type} holds {held}, which does not overlap the requested window",
            details={"barType": request.bar_type, "held": held},
        )


def execute(request: BacktestRequest, settings: Settings) -> RunOutcome:
    """Run a backtest to completion in this process and extract its reports."""
    from nautilus_trader.backtest.node import BacktestNode

    check_data_available(request, settings)
    spec = StrategySpec.model_validate(request.spec)
    config = build_run_config(request, spec, settings)

    expected_bars = len(
        Catalog.from_settings(settings).read_bars(
            request.bar_type, start=_to_ns(request.start), end=_to_ns(request.end)
        )
    )

    node = BacktestNode(configs=[config])
    node.run()
    engine = node.get_engines()[0]
    try:
        _assert_complete(engine, expected_bars)
        fills = engine.trader.generate_order_fills_report()
        positions = engine.trader.generate_positions_report()
        closed = (
            positions[positions["avg_px_close"].notna()]
            if "avg_px_close" in positions.columns
            else positions.iloc[0:0]
        )
        unrealized, open_count = _open_position_value(
            positions, engine, request, settings, price_precision=_price_precision(request, settings)
        )
        trades = build_trades(
            positions,
            fee_bps=request.fees.taker_bps,
            slippage_bps=request.slippage_bps,
            price_precision=_price_precision(request, settings),
        )
        starting_equity = _starting_equity(request)
        curve = build_equity_curve(trades, starting_equity)
        summary = summarise(
            trades,
            curve,
            starting_equity=starting_equity,
            start=request.start,
            end=request.end,
            unrealized_pnl=unrealized,
            open_positions=open_count,
        )

        return RunOutcome(
            fills=len(fills),
            positions=len(positions),
            closed_positions=len(closed),
            realized_pnl=_sum_money(positions.get("realized_pnl", [])),
            total_commission=_sum_money(fills.get("commissions", [])),
            summary=summary.to_dict(),
            trades=[trade.to_row() for trade in trades],
            equity_curve=[point.to_row() for point in curve],
        )
    finally:
        # Explicit, and after extraction (section 7.4).
        engine.dispose()


def _child(request_json: str, settings_json: str, outbox: Any) -> None:
    """Subprocess entry point. Never raises into the parent."""
    try:
        from engine.backtest.runner import execute  # re-import under spawn
        from engine.settings import Settings
        from engine.types.backtest import BacktestRequest

        outcome = execute(
            BacktestRequest.model_validate_json(request_json),
            Settings.model_validate_json(settings_json),
        )
        outbox.put(("ok", outcome.to_payload()))
    except BaseException as exc:  # noqa: BLE001 -- the boundary of a process
        # The traceback crosses as text and is logged by the parent. It is
        # never stored on the job record or returned to a caller (section 7.4).
        outbox.put(("error", type(exc).__name__, str(exc)[:500], traceback.format_exc()))


def _await_message(process: Any, outbox: Any, timeout: float) -> tuple[Any, ...]:
    """Wait for the child's answer, or for the child to stop existing.

    Polling rather than one long blocking get: a child that dies without
    reporting -- killed by the OOM killer, or crashed in a native extension --
    would otherwise leave the parent waiting out the entire timeout for an
    answer that is never coming.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            return tuple(outbox.get(timeout=_POLL_SECONDS))
        except queue_module.Empty:
            pass
        if not process.is_alive():
            # One more look: the child may have written just before exiting.
            try:
                return tuple(outbox.get_nowait())
            except queue_module.Empty:
                raise BacktestFailed(
                    f"the backtest process exited without a result (exit code {process.exitcode})"
                ) from None
        if time.monotonic() >= deadline:
            raise BacktestTimeout(f"backtest exceeded {timeout}s")


def run_isolated(
    request: BacktestRequest,
    settings: Settings,
    *,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    """Run a backtest in a fresh process, bounded by a wall clock.

    Raises ``BacktestTimeout`` if the ceiling is hit, ``BacktestFailed`` if the
    child raised. Either way the process is gone and its memory with it.
    """
    # Checked in the parent: spawning a process to discover the catalog is
    # empty costs a couple of seconds and returns a worse error.
    check_data_available(request, settings)

    timeout = timeout_seconds if timeout_seconds is not None else settings.backtest_timeout_seconds
    outbox: Any = _CONTEXT.Queue()
    process = _CONTEXT.Process(
        target=_child,
        args=(request.model_dump_json(), settings.model_dump_json(), outbox),
        daemon=True,
    )
    process.start()
    try:
        message = _await_message(process, outbox, timeout)
    finally:
        # Terminate unconditionally: on timeout it is still running, and on
        # success it has nothing left to do.
        if process.is_alive():
            process.terminate()
        process.join(timeout=10)
        if process.is_alive():  # pragma: no cover - only if terminate is ignored
            process.kill()
            process.join()

    if message[0] == "ok":
        result: dict[str, Any] = message[1]
        return result

    _, exception_name, detail, tb = message
    logger.error("backtest failed", extra={"exception": exception_name, "traceback": tb})
    raise BacktestFailed(f"{exception_name}: {detail}")
