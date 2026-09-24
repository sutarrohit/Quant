"""The one strategy class (spec section 6).

``DslStrategy`` receives a validated spec as a plain dict and interprets it. It
is never generated, and the identical class runs in backtest and live, so the
two cannot drift.

**Bar-close semantics.** Signals are evaluated on *closed* bars only: nothing
is decided from a bar still forming, and the catalog stores ``ts_event`` as the
bar close precisely so this holds.

The order fills **at that same bar's close**, not the next bar's open -- that is
Nautilus's measured behaviour (D12), and mildly optimistic. Spec section 6 asks
for next-bar fills; on BTCUSDT 15m the two differ by a median 0.00001% against a
30 bps round-trip, and a 24/7 market has no overnight gap for it to hide in.

**One position at a time per instrument** in v1, long-only: the schema has no
side, and the validator rejects pyramiding.

Nothing here reads a clock, a file or a socket. Time comes from ``self.clock``.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Protocol

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import Bar, BarType, InstrumentId
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.trading.strategy import Strategy

from engine.dsl.indicators import Series, build
from engine.dsl.interpreter import ConditionResult, EvalContext, evaluate, explain
from engine.dsl.keys import SeriesRef, required_refs
from engine.errors import StrategySetupError
from engine.live.gate import NoGate
from engine.strategies.sizing import InstrumentLimits, SizingOutcome, size_by_risk
from engine.types.dsl import RiskPercentSizing, StopLossPercent, StrategySpec, TakeProfitPercent
from engine.types.risk import AccountRisk, Decision, OrderIntent

logger = logging.getLogger(__name__)


class RiskGateLike(Protocol):
    """What the order path needs from a gate: a synchronous answer."""

    def check(self, intent: OrderIntent, account: AccountRisk, now_ns: int) -> Decision: ...


class RecorderLike(Protocol):
    """Where a live node's strategy reports what it did. Synchronous, in memory."""

    def record(self, kind: str, ts_ns: int, **fields: Any) -> None: ...


class DslStrategyConfig(StrategyConfig, frozen=True):
    """Config for one instrument.

    ``spec`` is the raw dict, already validated upstream by
    ``engine.dsl.validator`` -- this class re-parses it but does not re-decide
    whether it is sound. ``spec_hash`` identifies exactly which spec produced a
    result, and is what makes a stored backtest traceable.
    """

    instrument_id: InstrumentId
    bar_type: BarType
    spec: dict[str, Any]
    strategy_version_id: str
    spec_hash: str
    #: Total commission an order pays, in basis points. Sizing needs it to
    #: leave room to pay the fee on the position it is opening; without it a
    #: strategy sizing near 100% of equity overdraws the account and the
    #: simulated exchange halts the entire run.
    cost_bps: str = "0"


class DslStrategy(Strategy):  # type: ignore[misc]  # Strategy is a Cython class
    def __init__(self, config: DslStrategyConfig) -> None:
        super().__init__(config)
        self.spec: StrategySpec = StrategySpec.model_validate(config.spec)
        self.instrument: Instrument | None = None
        self._series: dict[str, Series] = {}
        # Values from the previous *evaluated* bar. Empty until the second one,
        # which is what makes a crossing return False during warmup rather
        # than guess (spec section 5.3).
        self._previous: dict[str, float] = {}
        self.bars_seen = 0
        self._stop_loss_percent = _stop_loss_percent(self.spec)
        self.orders_submitted = 0
        #: Commission as a fraction of notional, so sizing leaves room to
        #: pay it. The same figure the venue's fee model charges.
        self.cost_rate = Decimal(config.cost_bps) / Decimal(10_000)
        #: Consulted before every entry. A null object in backtest, replaced by
        #: a live ``RiskGate`` when a node builds this strategy, so backtest and
        #: live run the same order path (docs/adr-001-live-execution.md).
        self.risk_gate: RiskGateLike = NoGate()
        self.orders_blocked = 0
        #: Set on a live node, like `risk_gate`. None in a backtest, which then
        #: records nothing and explains nothing (docs/simulation-state-plan.md).
        self.recorder: RecorderLike | None = None
        self._take_profit_percent = _take_profit_percent(self.spec)
        self._last_bar: Bar | None = None
        self._checking: str | None = None
        self._conditions: list[ConditionResult] = []

    # --- lifecycle -------------------------------------------------------

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            # A missing instrument would otherwise produce an empty result that
            # looks exactly like a strategy which found no signals.
            raise StrategySetupError(
                f"instrument {self.config.instrument_id} is not in the cache; "
                "was it written to the catalog?",
            )

        self._resolve_cost_rate()
        self._series = self._build_series()
        self.subscribe_bars(self.config.bar_type)

        self.log.info(
            f"DslStrategy started: spec_hash={self.config.spec_hash} "
            f"series={sorted(self._series)} warmup={self.warmup_bars} bars",
        )

    def _resolve_cost_rate(self) -> None:
        """Charge sizing for the commission the venue will actually take.

        A backtest states its fees in the request -- mandatory, never defaulted
        (rule 5) -- and they reach here as ``cost_bps``. A live or simulation
        node has no request: the fee is whatever the venue charges, and the
        instrument it just fetched from that venue says what that is.

        So when nothing was configured, the instrument is the better authority
        and is used. Without this a simulation sizes as though trading were
        free, overdraws the account paying a commission it did not reserve for,
        and the simulated exchange **halts the run** -- the Phase 3 defect,
        which reported SUCCEEDED with three of forty-seven trades taken.

        Never silent: which source won is logged either way, because "why is
        my size different here" is otherwise unanswerable.
        """
        assert self.instrument is not None
        source = "config"
        if self.cost_rate == 0:
            taker = self.instrument.taker_fee
            if taker is not None and Decimal(str(taker)) > 0:
                self.cost_rate = Decimal(str(taker))
                source = "instrument"
        self.log.info(f"cost rate {self.cost_rate} (from {source})")
        logger.info(
            "cost rate resolved",
            extra={
                "strategy_version_id": self.config.strategy_version_id,
                "spec_hash": self.config.spec_hash,
                "cost_rate": str(self.cost_rate),
                "source": source,
            },
        )

    def on_stop(self) -> None:
        self.log.info(f"DslStrategy stopped after {self.bars_seen} bars")

    def on_reset(self) -> None:
        self._series = self._build_series()
        self._previous = {}
        self._last_bar = None
        self._checking = None
        self._conditions = []
        self.bars_seen = 0
        self.orders_submitted = 0
        self.orders_blocked = 0

    def _build_series(self) -> dict[str, Series]:
        """One instance per distinct series.

        Two conditions naming ``rsi`` with period 14 resolve to the same key and
        therefore share one instance, rather than computing the same numbers
        twice and drifting.
        """
        series: dict[str, Series] = {}
        for ref in self._required_refs():
            if ref.key not in series:
                series[ref.key] = build(ref)
        return series

    def _required_refs(self) -> list[SeriesRef]:
        refs: list[SeriesRef] = []
        for node in _indicator_conditions(self.spec):
            reference = getattr(node, "reference", None)
            refs.extend(
                required_refs(
                    node.indicator,
                    node.operator,
                    getattr(node, "period", None),
                    (reference.indicator, reference.period) if reference is not None else None,
                )
            )
        return refs

    @property
    def warmup_bars(self) -> int:
        """Bars before every series has a meaningful value."""
        from engine.dsl.indicators import warmup_bars as _warmup

        refs = self._required_refs()
        return max((_warmup(ref.name, ref.period) for ref in refs), default=0)

    # --- per bar ---------------------------------------------------------

    def on_bar(self, bar: Bar) -> None:
        #: Counted so the runner can verify the engine consumed all its
        #: data. A backtest that halts part-way otherwise returns a
        #: perfectly ordinary-looking result for the part that ran.
        self.bars_seen += 1
        self._last_bar = bar

        for series in self._series.values():
            series.handle_bar(bar)

        if not all(series.initialized for series in self._series.values()):
            return

        # Snapshot order matters: `previous` is the last evaluated bar's values,
        # captured before this bar's are recorded.
        previous = self._previous
        current = {key: series.value for key, series in self._series.items()}
        self._previous = current

        in_position, entry_price = self._position_state()
        context = EvalContext(
            values=current,
            previous=previous,
            close=bar.close.as_decimal(),
            in_position=in_position,
            entry_price=entry_price,
        )

        self._checking = "exit" if in_position else "entry"
        if self.recorder is not None:
            root = self.spec.exit_ if in_position else self.spec.entry
            self._conditions = explain(root, context, self._checking)

        if in_position:
            if self._decide("exit", self.spec.exit_, context, bar):
                self._exit(bar)
        elif self._decide("entry", self.spec.entry, context, bar):
            self._enter(bar)

    def _decide(self, side: str, node: object, context: EvalContext, bar: Bar) -> bool:
        """Evaluate one tree and log why.

        The values behind the decision are what later answer "why did the agent
        trade". Logged at DEBUG every bar because there are tens of thousands of
        them, and at INFO only when a signal actually fires.
        """
        triggered = evaluate(node, context)
        fields = {
            "strategy_version_id": self.config.strategy_version_id,
            "spec_hash": self.config.spec_hash,
            "instrument_id": str(self.config.instrument_id),
            "ts_event": bar.ts_event,
            "side": side,
            "triggered": triggered,
            "values": {key: round(value, 8) for key, value in sorted(context.values.items())},
        }
        logger.debug("signal evaluated", extra=fields)
        if triggered:
            logger.info("signal fired", extra=fields)
            self.log.info(f"{side} signal at {bar.ts_event}: {fields['values']}")
            self._record(
                "SIGNAL",
                bar.ts_event,
                side=side,
                close=str(context.close),
                values={key: str(round(value, 8)) for key, value in sorted(context.values.items())},
            )
        return triggered

    def _position_state(self) -> tuple[bool, Decimal | None]:
        """Open position for this instrument, if any.

        Orders are submitted in Step 11; until then this always reports flat,
        so entry conditions are the ones being exercised.
        """
        positions = self.cache.positions_open(instrument_id=self.config.instrument_id)
        if not positions:
            return False, None
        position = positions[0]
        return True, position.avg_px_open if isinstance(position.avg_px_open, Decimal) else Decimal(
            str(position.avg_px_open)
        )


    # --- orders ----------------------------------------------------------

    def _enter(self, bar: Bar) -> None:
        """Submit an entry for the *next* bar.

        Bar-close semantics: the signal was computed from a closed bar, so the
        order cannot fill inside it. One position at a time, and one order in
        flight -- without the pending check a repeated signal would stack
        positions while the first is still unfilled (spec section 6).
        """
        if self.cache.orders_open(instrument_id=self.config.instrument_id):
            return

        sizing = self._size(bar)
        fields = {
            "strategy_version_id": self.config.strategy_version_id,
            "spec_hash": self.config.spec_hash,
            "ts_event": bar.ts_event,
            "quantity": str(sizing.quantity),
            "notional": str(sizing.notional),
            "outcome": sizing.outcome.value,
        }
        if not sizing.placeable:
            logger.info("entry skipped", extra=fields)
            self._record(
                "ENTRY_SKIPPED",
                bar.ts_event,
                outcome=sizing.outcome.value,
                quantity=str(sizing.quantity),
                notional=str(sizing.notional),
            )
            return
        if sizing.outcome is not SizingOutcome.OK:
            logger.warning("entry size reduced", extra=fields)

        decision = self.risk_gate.check(
            OrderIntent(
                instrument_id=str(self.config.instrument_id),
                notional=sizing.notional,
                reduce_only=False,
            ),
            self._account_risk(),
            self.clock.timestamp_ns(),
        )
        if not decision.allowed:
            # Not an error: the account is being held back on purpose. WARNING
            # because an engaged kill switch and a limit binding every bar both
            # want to be visible.
            self.orders_blocked += 1
            logger.warning(
                "entry blocked by the risk gate",
                extra={
                    **fields,
                    "breach": decision.breach.value if decision.breach else None,
                    "reason": decision.reason,
                    # Which authority this was refused under. Without it the
                    # answer to "why did this order not go" needs two services'
                    # records joined by a timestamp (ADR-002).
                    "mandate_id": getattr(self.risk_gate, "mandate_id", None),
                },
            )
            self.log.warning(f"entry blocked: {decision.reason}")
            self._record(
                "ENTRY_BLOCKED",
                bar.ts_event,
                breach=decision.breach.value if decision.breach else None,
                reason=decision.reason,
                mandateId=getattr(self.risk_gate, "mandate_id", None),
            )
            return

        assert self.instrument is not None
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=self.instrument.make_qty(sizing.quantity),
        )
        self.submit_order(order)
        self.orders_submitted += 1
        logger.info("entry submitted", extra=fields)
        self._record(
            "ENTRY_SUBMITTED",
            bar.ts_event,
            clientOrderId=str(order.client_order_id),
            quantity=str(sizing.quantity),
            notional=str(sizing.notional),
        )

    def _exit(self, bar: Bar) -> None:
        positions = self.cache.positions_open(instrument_id=self.config.instrument_id)
        if not positions:
            return
        for position in positions:
            self.close_position(position)
            self._record("EXIT_SUBMITTED", bar.ts_event, quantity=str(position.quantity.as_decimal()))
        self.orders_submitted += 1
        logger.info(
            "exit submitted",
            extra={
                "strategy_version_id": self.config.strategy_version_id,
                "spec_hash": self.config.spec_hash,
                "ts_event": bar.ts_event,
            },
        )

    # --- what a live node reports ------------------------------------------

    def _record(self, kind: str, ts_ns: int, **fields: Any) -> None:
        if self.recorder is not None:
            self.recorder.record(kind, ts_ns, **fields)

    def on_order_filled(self, event: Any) -> None:
        # One event per fill, keyed by trade id: live fills orders in parts (L6).
        self._record(
            "FILL",
            event.ts_event,
            side=event.order_side.name,
            quantity=str(event.last_qty.as_decimal()),
            price=str(event.last_px.as_decimal()),
            commission={
                "amount": str(event.commission.as_decimal()),
                "currency": str(event.commission.currency),
            },
            tradeId=str(event.trade_id),
            clientOrderId=str(event.client_order_id),
        )

    def on_order_rejected(self, event: Any) -> None:
        self._record(
            "ORDER_REJECTED",
            event.ts_event,
            clientOrderId=str(event.client_order_id),
            reason=str(event.reason),
        )

    def on_position_closed(self, event: Any) -> None:
        self._record(
            "POSITION_CLOSED",
            event.ts_event,
            quantity=str(event.peak_qty.as_decimal()),
            entryPrice=str(event.avg_px_open),
            exitPrice=str(event.avg_px_close),
            realizedPnl={
                "amount": str(event.realized_pnl.as_decimal()),
                "currency": str(event.realized_pnl.currency),
            },
            openedAt=_iso(event.ts_opened),
            durationSeconds=event.duration_ns // 1_000_000_000,
        )

    def status(self) -> dict[str, Any]:
        """What the strategy is doing, as JSON. Read by the live publisher.

        The phase comes from the position *now*; the conditions from the last
        bar evaluated, which may predate a fill. Strings for every number (S4).
        """
        warming = self.bars_seen < self.warmup_bars or not all(
            series.initialized for series in self._series.values()
        )
        held = bool(self.cache.positions_open(instrument_id=self.config.instrument_id))
        phase = "WARMING_UP" if warming else "IN_POSITION" if held else "WAITING_FOR_ENTRY"
        bar = self._last_bar
        return {
            "phase": phase,
            "barsSeen": self.bars_seen,
            "warmupBars": self.warmup_bars,
            "barType": str(self.config.bar_type),
            "lastBar": (
                {"time": _iso(bar.ts_event), "close": str(bar.close.as_decimal())}
                if bar is not None
                else None
            ),
            "values": {key: str(round(value, 8)) for key, value in sorted(self._previous.items())},
            "lastEvaluation": (
                {
                    "side": self._checking,
                    "conditions": [
                        {"path": c.path, "label": c.label, "passed": c.passed, "series": c.series}
                        for c in self._conditions
                    ],
                }
                if self._checking is not None
                else None
            ),
            "stopLossPercent": str(self._stop_loss_percent),
            "takeProfitPercent": (
                str(self._take_profit_percent) if self._take_profit_percent is not None else None
            ),
            "ordersSubmitted": self.orders_submitted,
            "ordersBlocked": self.orders_blocked,
        }

    def _account_risk(self) -> AccountRisk:
        """What this account is carrying, as the gate needs to see it.

        Read from the cache rather than tracked incrementally: the cache is what
        survives a restart, and a counter kept in this object's memory would be
        wrong for exactly the run that had crashed.
        """
        open_notional = Decimal(0)
        positions = self.cache.positions_open()
        for position in positions:
            open_notional += Decimal(str(position.quantity)) * Decimal(str(position.avg_px_open))

        today = _date_of_ns(self.clock.timestamp_ns())
        realized = Decimal(0)
        for position in self.cache.positions_closed():
            if position.ts_closed is None or position.realized_pnl is None:
                continue
            if _date_of_ns(position.ts_closed) == today:
                realized += position.realized_pnl.as_decimal()

        return AccountRisk(
            open_notional=open_notional,
            open_positions=len(positions),
            realized_pnl_today=realized,
        )

    def _size(self, bar: Bar) -> Any:
        """Translate account and instrument state into the sizing inputs."""
        assert self.instrument is not None
        account = self.portfolio.account(self.config.instrument_id.venue)
        if account is None:
            raise StrategySetupError(f"no account for venue {self.config.instrument_id.venue}")

        currency = self.instrument.quote_currency
        equity = account.balance_total(currency).as_decimal()
        available = account.balance_free(currency).as_decimal()

        sizing_spec = self.spec.sizing
        if not isinstance(sizing_spec, RiskPercentSizing):
            raise StrategySetupError(f"unsupported sizing type: {type(sizing_spec).__name__}")

        return size_by_risk(
            equity=equity,
            available=available,
            price=bar.close.as_decimal(),
            risk_percent=sizing_spec.risk_percent,
            stop_loss_percent=self._stop_loss_percent,
            limits=InstrumentLimits(
                size_increment=self.instrument.size_increment.as_decimal(),
                min_quantity=self.instrument.min_quantity.as_decimal(),
                max_quantity=self.instrument.max_quantity.as_decimal(),
                min_notional=self.instrument.min_notional.as_decimal(),
            ),
            cost_rate=self.cost_rate,
        )


def _date_of_ns(ts_ns: int) -> date:
    """UTC calendar date of a Nautilus nanosecond timestamp.

    The daily loss limit resets on the UTC day: the only boundary a 24/7 crypto
    venue and this service agree on without a timezone argument.
    """
    return datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=UTC).date()


def _iso(ts_ns: int) -> str:
    return datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=UTC).isoformat().replace("+00:00", "Z")


def _take_profit_percent(spec: StrategySpec) -> Decimal | None:
    """The first take-profit in the exit tree, if any. For display only."""
    from engine.dsl.validator import walk

    for _, node in walk(spec.exit_, "exit"):
        if isinstance(node, TakeProfitPercent):
            return node.value
    return None


def _stop_loss_percent(spec: StrategySpec) -> Decimal:
    """The stop the risk budget is divided by.

    Guaranteed present by the validator for riskPercent sizing; raising here is
    the backstop for a spec that reached the engine without passing it.
    """
    from engine.dsl.validator import walk

    for _, node in walk(spec.exit_, "exit"):
        if isinstance(node, StopLossPercent):
            return node.value
    raise StrategySetupError(
        "riskPercent sizing divides by the stop distance, but the spec has no stopLossPercent",
    )


def _indicator_conditions(spec: StrategySpec) -> list[Any]:
    """Every indicator condition in the spec, entry and exit."""
    from engine.dsl.validator import walk

    found = []
    for root, node in (("entry", spec.entry), ("exit", spec.exit_)):
        for _, child in walk(node, root):
            if hasattr(child, "indicator") and hasattr(child, "operator"):
                found.append(child)
    return found
