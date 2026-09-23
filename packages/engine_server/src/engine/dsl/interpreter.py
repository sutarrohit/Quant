"""Condition evaluation (spec section 5.3).

``evaluate(node, ctx) -> bool``. That is the whole surface.

**Pure.** No I/O, no clock, no logging, no mutation, and nothing from Nautilus,
so it tests against hand-built contexts alone.

**No lookahead.** The context holds this bar, the previous bar and position
state. There is nowhere to put a future bar, which is the point.

**Nothing is swallowed.** An unknown operator, a missing series or an empty group
raises. A broad ``except`` returning ``False`` turns a broken strategy into a
silently inert one, indistinguishable from one that found no trades.

v1 is long-only: the schema has no side, and one position at a time per
instrument (spec section 6).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from engine.dsl.keys import SMA_OPERATORS, required_refs
from engine.errors import InterpreterError
from engine.types.dsl import (
    AllGroup,
    AnyGroup,
    NotGroup,
    Operator,
    StopLossPercent,
    TakeProfitPercent,
)

# Anything with an `indicator` attribute, structurally.
_INDICATOR_ATTRIBUTES = ("indicator", "operator")


@dataclass(frozen=True, slots=True)
class EvalContext:
    """Everything a condition may read, and nothing else.

    ``values`` and ``previous`` are keyed by ``engine.dsl.keys.series_key``.
    ``previous`` is missing a key during warmup, which is what makes a crossing
    return ``False`` rather than guess.
    """

    values: Mapping[str, float]
    previous: Mapping[str, float]
    close: Decimal
    in_position: bool = False
    entry_price: Decimal | None = None

    def value(self, key: str) -> float:
        try:
            return self.values[key]
        except KeyError as exc:
            raise InterpreterError(
                f"series {key!r} was not supplied; the strategy did not build it",
            ) from exc

    def previous_value(self, key: str) -> float | None:
        """Previous value, or ``None`` while warming up."""
        return self.previous.get(key)

    @property
    def unrealised_pnl_percent(self) -> Decimal:
        """Percent move from entry, long-only.

        Derived from ``entry_price`` and ``close`` rather than passed in, so it
        cannot disagree with the prices it is supposed to summarise. ``Decimal``
        throughout -- this decides exits, and exits are money.
        """
        if not self.in_position or self.entry_price is None:
            raise InterpreterError("unrealised PnL requested while flat")
        if self.entry_price <= 0:
            raise InterpreterError(f"entry price must be positive, got {self.entry_price}")
        return (self.close - self.entry_price) / self.entry_price * 100


def evaluate(node: object, ctx: EvalContext) -> bool:
    """Evaluate a condition tree."""
    if isinstance(node, AllGroup):
        return _all(node, ctx)
    if isinstance(node, AnyGroup):
        return _any(node, ctx)
    if isinstance(node, NotGroup):
        return not evaluate(node.not_, ctx)
    if isinstance(node, TakeProfitPercent):
        return ctx.unrealised_pnl_percent >= node.value
    if isinstance(node, StopLossPercent):
        return ctx.unrealised_pnl_percent <= -node.value
    if all(hasattr(node, attribute) for attribute in _INDICATOR_ATTRIBUTES):
        return _indicator(node, ctx)
    raise InterpreterError(f"cannot evaluate node of type {type(node).__name__}")


def _all(node: AllGroup, ctx: EvalContext) -> bool:
    if not node.all_:
        # `all([])` is True, which would enter on every bar. The validator
        # rejects empty groups; this is the backstop for when it does not.
        raise InterpreterError("`all` group is empty")
    return all(evaluate(child, ctx) for child in node.all_)


def _any(node: AnyGroup, ctx: EvalContext) -> bool:
    if not node.any_:
        raise InterpreterError("`any` group is empty")
    return any(evaluate(child, ctx) for child in node.any_)


def _indicator(node: object, ctx: EvalContext) -> bool:
    indicator: str = node.indicator  # type: ignore[attr-defined]
    operator: Operator = node.operator  # type: ignore[attr-defined]
    period: int | None = getattr(node, "period", None)
    threshold: Decimal | None = getattr(node, "value", None)
    reference_spec = getattr(node, "reference", None)

    reference_pair = (
        (reference_spec.indicator, reference_spec.period) if reference_spec is not None else None
    )
    refs = required_refs(indicator, operator, period, reference_pair)
    current = ctx.value(refs[0].key)

    if reference_spec is not None or operator in SMA_OPERATORS:
        # The comparison moves. A crossing therefore needs the previous value
        # of the reference too, not just of the subject.
        reference_key = refs[-1].key
        reference = ctx.value(reference_key)
        previous_reference = ctx.previous_value(reference_key)
    else:
        if threshold is None:
            raise InterpreterError(f"{indicator}.{operator.value} needs a `value` to compare against")
        # A fixed threshold is its own previous value.
        reference = previous_reference = float(threshold)

    match operator:
        case Operator.GREATER_THAN | Operator.GREATER_THAN_SMA:
            return current > reference
        case Operator.LESS_THAN | Operator.LESS_THAN_SMA:
            return current < reference
        case Operator.CROSSES_ABOVE:
            return _crosses(ctx, refs[0].key, current, reference, previous_reference, above=True)
        case Operator.CROSSES_BELOW:
            return _crosses(ctx, refs[0].key, current, reference, previous_reference, above=False)
        case _:
            raise InterpreterError(f"unknown operator: {operator!r}")


def _crosses(
    ctx: EvalContext,
    key: str,
    current: float,
    reference: float,
    previous_reference: float | None,
    *,
    above: bool,
) -> bool:
    """A crossing needs two bars, and both sides of the comparison.

    ``crossesAbove`` is: the subject was at or below the reference on the
    previous bar, and is above it now. It is true on the bar the lines cross
    and not on the ones after.

    When the reference is another series -- a moving average, say -- its
    *previous* value is what the subject must have been below, not its current
    one. Comparing yesterday's fast average against today's slow average would
    report crossings that never happened, and miss ones that did.

    During warmup either side may be unavailable, and the answer is ``False``
    rather than a guess (spec section 5.3).
    """
    previous = ctx.previous_value(key)
    if previous is None or previous_reference is None:
        return False
    if above:
        return previous <= previous_reference and current > reference
    return previous >= previous_reference and current < reference
