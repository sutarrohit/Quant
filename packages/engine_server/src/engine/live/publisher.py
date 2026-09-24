"""What a running account is doing, published as JSON (docs/simulation-state-plan.md).

A node's trading state -- balances, the position, what the strategy is waiting
for -- lives in its own process. The only thing that used to leave it was the
heartbeat. This is the second channel, and the rule is the same: **only JSON
crosses**, written to the control-plane Redis. Nautilus's cache stays private to
the node; its layout is Nautilus's to change.

Three shapes, three structures:

* **snapshot** -- the latest state, one key, rewritten every tick;
* **events** -- fills, signals, blocked entries, as a capped stream;
* **equity** -- one point per closed bar, as a capped stream.

Streams, because an entry id is a timestamp: "everything after the last one I
saw" is one `XRANGE`, which is what a polling page wants.

**Mode-neutral** (plan section 8): nothing here branches on SIMULATION. Live
reuses it as it stands; the mode is a field.

**An allowlist, never a dump** (L8). The snapshot is assembled field by field,
so a credential reference on the desired state cannot reach it.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from engine.types.state import DesiredState

logger = logging.getLogger(__name__)

SNAPSHOT_KEY = "live:snapshot:{account_id}"
EVENTS_KEY = "live:events:{account_id}"
EQUITY_KEY = "live:equity:{account_id}"
BASELINE_KEY = "live:baseline:{account_id}"

#: Roughly a week of an active strategy's activity. Trimmed approximately, which
#: is what keeps `XADD` O(1).
EVENTS_MAXLEN = 1_000
#: 52 days of 15-minute bars.
EQUITY_MAXLEN = 5_000
#: Events waiting for the publisher. Bounded, so a Redis that is down costs the
#: oldest events rather than the node's memory.
PENDING_MAX = 1_000

DUST = Decimal("0.00000001")


def iso(ts_ns: int) -> str:
    return datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=UTC).isoformat().replace("+00:00", "Z")


def num(value: Decimal) -> str:
    """Plain decimal text: ``0``, not ``0E-10``; ``10000``, not ``1E+4``."""
    return format(value.normalize(), "f")


def money(value: Any) -> dict[str, str]:
    """A Nautilus `Money` as `{amount, currency}`. Never assume the currency (L5)."""
    return {"amount": str(value.as_decimal()), "currency": str(value.currency)}


class EventRecorder:
    """The strategy's side: synchronous and in memory.

    Strategy callbacks run on the node's loop and must not await Redis, so they
    append here and the publisher drains on its tick. A slow Redis then delays
    the activity feed, not the order path.
    """

    def __init__(self, maxlen: int = PENDING_MAX) -> None:
        self._pending: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def record(self, kind: str, ts_ns: int, **fields: Any) -> None:
        self._pending.append({"kind": kind, "at": iso(ts_ns), **fields})

    def drain(self) -> list[dict[str, Any]]:
        drained = list(self._pending)
        self._pending.clear()
        return drained

    def put_back(self, events: list[dict[str, Any]]) -> None:
        """Return events a failed write did not deliver, oldest first."""
        self._pending.extendleft(reversed(events))


# --- the snapshot ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Baseline:
    """What the account was worth when it was first seen (L2).

    Recorded, not assumed: live starts with whatever the exchange account holds.
    """

    currency: str
    amount: Decimal
    at: str

    def to_json(self) -> dict[str, str]:
        return {"currency": self.currency, "amount": num(self.amount), "at": self.at}

    @classmethod
    def from_json(cls, raw: str) -> Baseline:
        data = json.loads(raw)
        return cls(currency=data["currency"], amount=Decimal(data["amount"]), at=data["at"])


def build_snapshot(
    state: DesiredState,
    cache: Any,
    strategy: dict[str, Any] | None,
    *,
    baseline: Baseline | None,
    now_ns: int,
    session_started_at: str,
    kill_engaged: bool,
    mandate_revoked: bool,
) -> dict[str, Any]:
    """The account as the page shows it. Pure over what it is handed.

    **Scoped to the instrument** (L4): equity is its quote balance plus its base
    balance at the last price. Anything else the account holds is listed under
    ``otherHoldings`` and left out of the performance numbers.

    **P&L is equity over the baseline**, split into unrealised (the open
    position at the last price) and realised (the rest). Not Nautilus's
    `realized_pnl`: on a NETTING account a reopened position reuses its id, the
    earlier cycle's result lives only in memory, and a restart drops it (D27).

    Exact for a simulation. Live will also need deposits and withdrawals netted
    out of the baseline (L3) -- a deposit moves equity without a trade.
    """
    from nautilus_trader.model.identifiers import InstrumentId, Venue

    instrument_id = InstrumentId.from_str(state.instrument_id)
    instrument = cache.instrument(instrument_id)
    quote = str(instrument.quote_currency) if instrument is not None else None
    base = str(instrument.base_currency) if instrument is not None else None

    last_bar = (strategy or {}).get("lastBar")
    open_positions = cache.positions_open(instrument_id=instrument_id)
    position = open_positions[0] if open_positions else None
    last_price = (
        Decimal(last_bar["close"])
        if last_bar
        else Decimal(str(position.avg_px_open))
        if position is not None
        else None
    )

    balances: list[dict[str, str]] = []
    other: list[dict[str, str]] = []
    held: dict[str, Decimal] = {}
    account = cache.account_for_venue(Venue(state.venue))
    if account is not None:
        for currency, total in account.balances_total().items():
            amount = total.as_decimal()
            if amount.copy_abs() < DUST:
                continue
            code = str(currency)
            row = {
                "currency": code,
                "total": num(amount),
                "free": num(account.balance_free(currency).as_decimal()),
                "locked": num(account.balance_locked(currency).as_decimal()),
            }
            (balances if code in (quote, base) else other).append(row)
            held[code] = amount

    equity: Decimal | None = None
    if quote is not None:
        base_held = held.get(base or "", Decimal(0))
        if base_held == 0:
            equity = held.get(quote, Decimal(0))
        elif last_price is not None:
            equity = held.get(quote, Decimal(0)) + base_held * last_price

    unrealized_pnl = Decimal(0)
    position_json = None
    if position is not None:
        quantity = Decimal(str(position.quantity))
        avg_entry = Decimal(str(position.avg_px_open))
        if last_price is not None:
            unrealized_pnl = (last_price - avg_entry) * quantity
        stop = (strategy or {}).get("stopLossPercent")
        take = (strategy or {}).get("takeProfitPercent")
        position_json = {
            "side": position.side.name,
            "quantity": num(quantity),
            "avgEntry": num(avg_entry),
            "lastPrice": num(last_price) if last_price is not None else None,
            "unrealizedPnl": num(unrealized_pnl),
            "openedAt": iso(position.ts_opened),
            "stopPrice": num(avg_entry * (1 - Decimal(stop) / 100)) if stop else None,
            "takeProfitPrice": num(avg_entry * (1 + Decimal(take) / 100)) if take else None,
        }

    pnl = equity - baseline.amount if equity is not None and baseline is not None else None
    realized_pnl = pnl - unrealized_pnl if pnl is not None else None
    return {
        "accountId": state.account_id,
        "mode": state.mode.value,
        "at": iso(now_ns),
        "sessionStartedAt": session_started_at,
        "revision": state.revision,
        "instrumentId": state.instrument_id,
        "quoteCurrency": quote,
        "baseline": baseline.to_json() if baseline is not None else None,
        "equity": num(equity) if equity is not None else None,
        "realizedPnl": num(realized_pnl) if realized_pnl is not None else None,
        "unrealizedPnl": num(unrealized_pnl),
        "pnl": num(pnl) if pnl is not None else None,
        "returnPercent": return_percent(pnl, baseline),
        "balances": balances,
        "otherHoldings": other,
        "position": position_json,
        "openOrders": [
            {
                "clientOrderId": str(order.client_order_id),
                "side": order.side.name,
                "type": order.order_type.name,
                "quantity": num(order.quantity.as_decimal()),
                "status": order.status.name,
                "submittedAt": iso(order.ts_init),
            }
            for order in cache.orders_open(instrument_id=instrument_id)
        ],
        "killSwitch": kill_engaged,
        "mandateRevoked": mandate_revoked,
        "strategy": strategy,
    }


def return_percent(pnl: Decimal | None, baseline: Baseline | None) -> str | None:
    if pnl is None or baseline is None or baseline.amount <= 0:
        return None
    return num((pnl / baseline.amount * 100).quantize(Decimal("0.00000001")))


# --- writing ---------------------------------------------------------------


class StatePublisher:
    """The node's side: writes what the recorder and the node hold, on each tick.

    Called from the worker's `tend` loop, on the node's own event loop, so
    reading the cache here is not a race.
    """

    def __init__(
        self,
        redis: Any,
        state: DesiredState,
        node: Any,
        recorder: EventRecorder,
        *,
        started_at_ns: int | None = None,
    ) -> None:
        self._redis = redis
        self._state = state
        self._node = node
        self._recorder = recorder
        self._session_started_at = iso(started_at_ns or time.time_ns())
        self._baseline: Baseline | None = None
        self._last_equity_bar: str | None = None

    def _key(self, template: str) -> str:
        return template.format(account_id=self._state.account_id)

    def note(self, kind: str, **fields: Any) -> None:
        """Queue one of the worker's own events: start, stop, kill. Written next tick."""
        self._recorder.record(kind, time.time_ns(), **fields)

    async def flush_events(self) -> None:
        events = self._recorder.drain()
        if not events:
            return
        try:
            pipe = self._redis.pipeline()
            for event in events:
                pipe.xadd(
                    self._key(EVENTS_KEY),
                    {"data": json.dumps(event)},
                    maxlen=EVENTS_MAXLEN,
                    approximate=True,
                )
            await pipe.execute()
        except Exception:
            self._recorder.put_back(events)
            raise

    async def publish(self, *, kill_engaged: bool = False, mandate_revoked: bool = False) -> None:
        """One tick: events, then the snapshot, then an equity point on a new bar."""
        await self.flush_events()

        strategy = self._strategy_status()
        snapshot = self._build(strategy, kill_engaged, mandate_revoked)
        if self._baseline is None and snapshot["equity"] is not None:
            self._baseline = await self._record_baseline(snapshot)
            snapshot = self._build(strategy, kill_engaged, mandate_revoked)
        await self._redis.set(self._key(SNAPSHOT_KEY), json.dumps(snapshot))

        last_bar = (strategy or {}).get("lastBar")
        if last_bar and snapshot["equity"] is not None and last_bar["time"] != self._last_equity_bar:
            await self._redis.xadd(
                self._key(EQUITY_KEY),
                {"time": last_bar["time"], "equity": snapshot["equity"]},
                maxlen=EQUITY_MAXLEN,
                approximate=True,
            )
            self._last_equity_bar = last_bar["time"]

    def _build(
        self, strategy: dict[str, Any] | None, kill_engaged: bool, mandate_revoked: bool
    ) -> dict[str, Any]:
        return build_snapshot(
            self._state,
            self._node.cache,
            strategy,
            baseline=self._baseline,
            now_ns=time.time_ns(),
            session_started_at=self._session_started_at,
            kill_engaged=kill_engaged,
            mandate_revoked=mandate_revoked,
        )

    async def _record_baseline(self, snapshot: dict[str, Any]) -> Baseline:
        """First value wins, across restarts: `SET NX`, then read back."""
        first = Baseline(
            currency=snapshot["quoteCurrency"],
            amount=Decimal(snapshot["equity"]),
            at=snapshot["at"],
        )
        await self._redis.set(self._key(BASELINE_KEY), json.dumps(first.to_json()), nx=True)
        raw = await self._redis.get(self._key(BASELINE_KEY))
        return Baseline.from_json(raw) if raw else first

    def _strategy_status(self) -> dict[str, Any] | None:
        for strategy in self._node.trader.strategies():
            status = getattr(strategy, "status", None)
            if callable(status):
                result: dict[str, Any] = status()
                return result
        return None


# --- reading ---------------------------------------------------------------


class StateFeed:
    """The API's side. Reads what `StatePublisher` wrote; never the node."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def snapshot(self, account_id: str) -> dict[str, Any] | None:
        raw = await self._redis.get(SNAPSHOT_KEY.format(account_id=account_id))
        return json.loads(raw) if raw else None

    async def events(
        self, account_id: str, *, after: str | None, limit: int
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Oldest first. Without `after`, the latest `limit`; with it, what came since."""
        key = EVENTS_KEY.format(account_id=account_id)
        if after is None:
            entries = list(reversed(await self._redis.xrevrange(key, count=limit)))
        else:
            entries = await self._redis.xrange(key, min=f"({after}", count=limit)
        events = [{"id": entry_id, **json.loads(fields["data"])} for entry_id, fields in entries]
        return events, (entries[-1][0] if entries else after)

    async def equity(
        self, account_id: str, *, after: str | None
    ) -> tuple[list[dict[str, str]], str | None]:
        key = EQUITY_KEY.format(account_id=account_id)
        entries = await self._redis.xrange(key, min=f"({after}" if after else "-")
        points = [{"time": fields["time"], "equity": fields["equity"]} for _, fields in entries]
        return points, (entries[-1][0] if entries else after)

    async def forget(self, account_id: str) -> None:
        for template in (SNAPSHOT_KEY, EVENTS_KEY, EQUITY_KEY, BASELINE_KEY):
            await self._redis.delete(template.format(account_id=account_id))
