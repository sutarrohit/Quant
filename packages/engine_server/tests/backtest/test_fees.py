from __future__ import annotations

from decimal import Decimal as D

import pytest
from nautilus_trader.model.enums import OrderSide, OrderType
from nautilus_trader.model.objects import Currency, Price, Quantity

from engine.backtest.fees import BpsFeeModel, BpsFeeModelConfig, split_cost

USDT = Currency.from_str("USDT")


class FakeInstrument:
    quote_currency = USDT


class FakeOrder:
    def __init__(self, order_type: OrderType = OrderType.MARKET) -> None:
        self.order_type = order_type
        self.side = OrderSide.BUY


def model(maker: str = "1", taker: str = "10", slippage: str = "5") -> BpsFeeModel:
    return BpsFeeModel(
        BpsFeeModelConfig(maker_bps=maker, taker_bps=taker, slippage_bps=slippage)
    )


def commission(fee_model: BpsFeeModel, qty: str, price: str, order_type: OrderType) -> D:
    money = fee_model.get_commission(
        FakeOrder(order_type), Quantity.from_str(qty), Price.from_str(price), FakeInstrument()
    )
    return money.as_decimal()


# --- the arithmetic ------------------------------------------------------


def test_a_market_order_pays_taker_plus_slippage() -> None:
    # 0.1 BTC at 40000 = 4000 notional. 10 + 5 = 15 bps = 6 USDT.
    assert commission(model(), "0.1", "40000.00", OrderType.MARKET) == D(6)


def test_a_limit_order_pays_maker_plus_slippage() -> None:
    # 1 + 5 = 6 bps of 4000 = 2.4 USDT.
    assert commission(model(), "0.1", "40000.00", OrderType.LIMIT) == D("2.4")


def test_cost_scales_with_notional() -> None:
    fee_model = model()
    small = commission(fee_model, "0.1", "40000.00", OrderType.MARKET)
    large = commission(fee_model, "1.0", "40000.00", OrderType.MARKET)
    assert large == small * 10


def test_zero_costs_charge_nothing() -> None:
    assert commission(model("0", "0", "0"), "1.0", "40000.00", OrderType.MARKET) == 0


def test_slippage_alone_is_charged() -> None:
    # 5 bps of 40000 = 20 USDT, with no venue fee at all.
    assert commission(model("0", "0", "5"), "1.0", "40000.00", OrderType.MARKET) == D(20)


def test_fractional_basis_points() -> None:
    assert commission(model("0", "7.5", "0"), "1.0", "40000.00", OrderType.MARKET) == D(30)


# --- inputs --------------------------------------------------------------


@pytest.mark.parametrize("field", ["maker_bps", "taker_bps", "slippage_bps"])
def test_negative_costs_are_rejected(field: str) -> None:
    values = {"maker_bps": "1", "taker_bps": "10", "slippage_bps": "5", field: "-1"}
    with pytest.raises(ValueError, match="must not be negative"):
        BpsFeeModel(BpsFeeModelConfig(**values))  # type: ignore[arg-type]


def test_costs_are_parsed_as_decimal_not_float() -> None:
    fee_model = model("0.1", "0.2", "0.3")
    assert isinstance(fee_model.maker_bps, D)
    # 0.1 + 0.2 is exact here, which it would not be in binary floating point.
    assert fee_model.maker_bps + fee_model.taker_bps == D("0.3")


# --- determinism ---------------------------------------------------------


def test_the_same_fill_always_costs_the_same() -> None:
    # No clock, no randomness -- unlike Nautilus's probabilistic fill models,
    # which would put a random number generator in an output path.
    fee_model = model()
    costs = {commission(fee_model, "0.1", "40000.00", OrderType.MARKET) for _ in range(5)}
    assert len(costs) == 1


# --- attribution ---------------------------------------------------------


def test_cost_splits_back_into_fees_and_slippage() -> None:
    # Spec section 7.5 reports the two separately. Both are exact functions of
    # the notional, so the split is arithmetic, not an estimate.
    fees, slippage = split_cost(D(4000), fee_bps=D(10), slippage_bps=D(5))
    assert fees == D(4)
    assert slippage == D(2)
    assert fees + slippage == commission(model(), "0.1", "40000.00", OrderType.MARKET)


def test_split_is_exact_for_fractional_rates() -> None:
    fees, slippage = split_cost(D(10000), fee_bps=D("2.5"), slippage_bps=D("0.5"))
    assert fees == D("2.5")
    assert slippage == D("0.5")
