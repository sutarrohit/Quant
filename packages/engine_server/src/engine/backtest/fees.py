"""Trading costs charged in basis points.

Spec section 7.3 makes fees and slippage **mandatory request inputs**. Nautilus
offers neither in that form:

* ``MakerTakerFeeModel`` reads ``maker_fee``/``taker_fee`` off the *instrument*.
  Ours are zero, because public ``exchangeInfo`` carries no fee tiers (D4), and
  a fee guessed at ingest would silently become the number every result is
  built on.
* ``FillModel`` slippage is one tick, or probabilistic with a random seed.
  One tick on BTCUSDT is 0.01 against a ~42,000 price -- about 0.0024 bps,
  three orders of magnitude short of a realistic 5. The probabilistic models
  would also put a random number generator in an output path, which section 12
  forbids.

So both are charged here, as commission proportional to notional. For a market
order that is economically identical to filling at a worse price, and it has
two advantages: the recorded fill price stays the venue's, and the cost is
attributable -- section 7.5 wants fees and slippage reported separately, and
both are exactly ``notional x bps / 10_000``, reconstructable after the fact
without guessing.

Deterministic by construction: no clock, no randomness.
"""

from __future__ import annotations

from decimal import Decimal

from nautilus_trader.backtest.models import FeeModel
from nautilus_trader.config import NautilusConfig
from nautilus_trader.model.enums import OrderType
from nautilus_trader.model.objects import Money

BPS = Decimal(10_000)


class BpsFeeModelConfig(NautilusConfig, frozen=True):
    """Costs as basis-point strings.

    Strings, not floats: these multiply every notional in the result, and a
    float here is a rounding error compounded across every trade.
    """

    maker_bps: str
    taker_bps: str
    slippage_bps: str


class BpsFeeModel(FeeModel):  # type: ignore[misc]  # FeeModel is a Cython class
    """Charges ``notional x (fee_bps + slippage_bps) / 10_000`` per fill."""

    def __init__(self, config: BpsFeeModelConfig) -> None:
        super().__init__()
        self.maker_bps = Decimal(config.maker_bps)
        self.taker_bps = Decimal(config.taker_bps)
        self.slippage_bps = Decimal(config.slippage_bps)
        for name, value in (
            ("maker_bps", self.maker_bps),
            ("taker_bps", self.taker_bps),
            ("slippage_bps", self.slippage_bps),
        ):
            if value < 0:
                raise ValueError(f"{name} must not be negative, got {value}")

    def get_commission(
        self,
        order: object,
        fill_qty: object,
        fill_px: object,
        instrument: object,
    ) -> Money:
        notional = Decimal(str(fill_qty)) * Decimal(str(fill_px))
        # v1 submits market orders, which always take liquidity. A resting
        # limit order would earn the maker rate.
        taking = getattr(order, "order_type", None) != OrderType.LIMIT
        fee_bps = self.taker_bps if taking else self.maker_bps
        cost = notional * (fee_bps + self.slippage_bps) / BPS
        return Money(cost, instrument.quote_currency)  # type: ignore[attr-defined]


def split_cost(notional: Decimal, fee_bps: Decimal, slippage_bps: Decimal) -> tuple[Decimal, Decimal]:
    """Attribute a charged commission back to fees and slippage.

    Both components are exact functions of the notional, so the split is
    arithmetic rather than an estimate. Used by result reporting (Step 16).
    """
    return notional * fee_bps / BPS, notional * slippage_bps / BPS
