"""Position sizing (spec section 6).

Pure arithmetic on ``Decimal``. No Nautilus, no account objects -- the caller
extracts the numbers and passes them in, which is what makes the one piece of
maths that decides how much money is at risk unit-testable on its own.

The rule, for ``riskPercent`` sizing:

    quantity = (equity x riskPercent) / (entry_price x stopLossPercent)

Losing ``stopLossPercent`` of the position then costs exactly ``riskPercent``
of equity. The two percentage denominators cancel, which is why neither
appears.

**Rounding is always down.** ``Quantity`` rounds to nearest, and rounding *up*
to the venue's step would put more at risk than the budget allows -- a small
error, silently, on every trade.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum


class SizingOutcome(StrEnum):
    OK = "OK"
    #: Reduced to what the account can actually pay for. The position is
    #: smaller than the risk budget allows, never larger.
    CAPPED_BY_BALANCE = "CAPPED_BY_BALANCE"
    CAPPED_BY_MAX_QUANTITY = "CAPPED_BY_MAX_QUANTITY"
    BELOW_MIN_QUANTITY = "BELOW_MIN_QUANTITY"
    BELOW_MIN_NOTIONAL = "BELOW_MIN_NOTIONAL"


@dataclass(frozen=True, slots=True)
class InstrumentLimits:
    """What the venue will accept. Straight from exchange metadata."""

    size_increment: Decimal
    min_quantity: Decimal
    max_quantity: Decimal
    min_notional: Decimal


@dataclass(frozen=True, slots=True)
class Sizing:
    quantity: Decimal
    notional: Decimal
    outcome: SizingOutcome

    @property
    def placeable(self) -> bool:
        return self.quantity > 0 and self.outcome in (
            SizingOutcome.OK,
            SizingOutcome.CAPPED_BY_BALANCE,
            SizingOutcome.CAPPED_BY_MAX_QUANTITY,
        )


def floor_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    """Round down to a multiple of the venue's step size."""
    if increment <= 0:
        raise ValueError(f"size increment must be positive, got {increment}")
    return (value / increment).to_integral_value(rounding=ROUND_DOWN) * increment


def size_by_risk(
    *,
    equity: Decimal,
    available: Decimal,
    price: Decimal,
    risk_percent: Decimal,
    stop_loss_percent: Decimal,
    limits: InstrumentLimits,
    cost_rate: Decimal = Decimal(0),
) -> Sizing:
    """How much to buy, given a risk budget and where the stop sits.

    ``equity`` sets the budget; ``available`` is what the account can actually
    spend. On a cash account they differ once capital is committed, and a
    position larger than the balance is simply rejected by the venue -- so it
    is capped here, and the caller is told it happened.

    ``cost_rate`` is the commission as a fraction of notional. The affordable
    quantity is ``available / (price * (1 + cost_rate))``, not
    ``available / price``: a position that spends the entire balance cannot
    also pay the fee on itself. Nautilus does not reject such an order -- it
    fills it, the balance goes negative, and the simulated exchange **halts the
    whole backtest**, silently truncating a run that then reports as
    successful. Found on a strategy sizing near 100% of equity; a position at
    half the balance always had the headroom to hide it.
    """
    if price <= 0:
        raise ValueError(f"price must be positive, got {price}")
    if stop_loss_percent <= 0:
        raise ValueError(f"stop loss percent must be positive, got {stop_loss_percent}")
    if risk_percent <= 0:
        raise ValueError(f"risk percent must be positive, got {risk_percent}")

    outcome = SizingOutcome.OK

    # The percentage denominators cancel: (equity * r/100) / (price * s/100).
    quantity = (equity * risk_percent) / (price * stop_loss_percent)

    affordable = available / (price * (1 + cost_rate))
    if quantity > affordable:
        quantity = affordable
        outcome = SizingOutcome.CAPPED_BY_BALANCE

    if quantity > limits.max_quantity:
        quantity = limits.max_quantity
        outcome = SizingOutcome.CAPPED_BY_MAX_QUANTITY

    quantity = floor_to_increment(quantity, limits.size_increment)
    notional = quantity * price

    if quantity < limits.min_quantity:
        return Sizing(Decimal(0), Decimal(0), SizingOutcome.BELOW_MIN_QUANTITY)
    if notional < limits.min_notional:
        return Sizing(Decimal(0), Decimal(0), SizingOutcome.BELOW_MIN_NOTIONAL)

    return Sizing(quantity, notional, outcome)
