from __future__ import annotations

from decimal import Decimal as D

import pytest

from engine.strategies.sizing import (
    InstrumentLimits,
    SizingOutcome,
    floor_to_increment,
    size_by_risk,
)

BTC = InstrumentLimits(
    size_increment=D("0.00001"),
    min_quantity=D("0.00001"),
    max_quantity=D("9000"),
    min_notional=D("5"),
)


def size(**overrides: object) -> object:
    kwargs: dict[str, object] = {
        "equity": D(10000),
        "available": D(10000),
        "price": D(40000),
        "risk_percent": D(1),
        "stop_loss_percent": D(2),
        "limits": BTC,
    }
    kwargs.update(overrides)
    return size_by_risk(**kwargs)  # type: ignore[arg-type]


# --- the rule ------------------------------------------------------------


def test_risk_budget_is_exactly_the_percentage_of_equity() -> None:
    # 10000 equity, 1% risk, 2% stop, 40000 price.
    # qty = 10000 * 1 / (40000 * 2) = 0.125
    result = size()
    assert result.quantity == D("0.125")  # type: ignore[attr-defined]
    assert result.notional == D("5000.000")  # type: ignore[attr-defined]
    # Being stopped out costs exactly 1% of equity.
    assert result.notional * D(2) / 100 == D(100)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("risk", "stop", "expected_loss"),
    [(D(1), D(2), D(100)), (D(2), D(2), D(200)), (D(1), D(5), D(100)), (D("0.5"), D(1), D(50))],
)
def test_loss_at_the_stop_always_equals_the_budget(
    risk: D, stop: D, expected_loss: D
) -> None:
    result = size(risk_percent=risk, stop_loss_percent=stop)
    assert result.notional * stop / 100 == pytest.approx(expected_loss)  # type: ignore[attr-defined]


def test_a_tighter_stop_buys_more() -> None:
    tight = size(stop_loss_percent=D(1)).quantity  # type: ignore[attr-defined]
    wide = size(stop_loss_percent=D(4)).quantity  # type: ignore[attr-defined]
    assert tight == wide * 4


# --- rounding down -------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "increment", "expected"),
    [
        ("0.123456789", "0.00001", "0.12345"),
        ("0.99999999", "0.00001", "0.99999"),
        ("1.0", "0.00001", "1.0"),
        ("7.9", "1", "7"),
        ("0.000009", "0.00001", "0"),
    ],
)
def test_floor_to_increment(value: str, increment: str, expected: str) -> None:
    assert floor_to_increment(D(value), D(increment)) == D(expected)


def test_quantity_is_rounded_down_never_up() -> None:
    # Quantity.make_qty rounds to NEAREST. Rounding up to the venue step would
    # put more at risk than the budget allows, silently, on every trade.
    result = size(price=D(43210), limits=InstrumentLimits(D("0.001"), D("0.001"), D(9000), D(5)))
    raw = D(10000) * D(1) / (D(43210) * D(2))
    assert result.quantity <= raw  # type: ignore[attr-defined]
    assert result.quantity == floor_to_increment(raw, D("0.001"))  # type: ignore[attr-defined]


def test_a_zero_increment_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        floor_to_increment(D(1), D(0))


# --- caps ----------------------------------------------------------------


def test_capped_by_available_balance() -> None:
    # 1% risk with a 0.5% stop wants 2x the account. The venue would reject it.
    result = size(stop_loss_percent=D("0.5"))
    assert result.outcome is SizingOutcome.CAPPED_BY_BALANCE  # type: ignore[attr-defined]
    assert result.notional <= D(10000)  # type: ignore[attr-defined]
    assert result.placeable  # type: ignore[attr-defined]


def test_capping_never_increases_the_position() -> None:
    uncapped = size(available=D(1_000_000)).quantity  # type: ignore[attr-defined]
    capped = size(available=D(100)).quantity  # type: ignore[attr-defined]
    assert capped < uncapped


def test_capped_by_max_quantity() -> None:
    limits = InstrumentLimits(D("0.00001"), D("0.00001"), D("0.01"), D(5))
    result = size(limits=limits)
    assert result.outcome is SizingOutcome.CAPPED_BY_MAX_QUANTITY  # type: ignore[attr-defined]
    assert result.quantity == D("0.01")  # type: ignore[attr-defined]


# --- rejections ----------------------------------------------------------


def test_below_min_quantity_is_not_placeable() -> None:
    limits = InstrumentLimits(D("0.00001"), D("1"), D(9000), D(5))
    result = size(limits=limits)
    assert result.outcome is SizingOutcome.BELOW_MIN_QUANTITY  # type: ignore[attr-defined]
    assert result.quantity == 0  # type: ignore[attr-defined]
    assert not result.placeable  # type: ignore[attr-defined]


def test_below_min_notional_is_not_placeable() -> None:
    result = size(equity=D(10), available=D(10))
    assert result.outcome is SizingOutcome.BELOW_MIN_NOTIONAL  # type: ignore[attr-defined]
    assert not result.placeable  # type: ignore[attr-defined]


def test_a_tiny_account_produces_no_order_rather_than_a_bad_one() -> None:
    result = size(equity=D("0.01"), available=D("0.01"))
    assert result.quantity == 0  # type: ignore[attr-defined]
    assert not result.placeable  # type: ignore[attr-defined]


# --- inputs --------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("price", D(0), "price must be positive"),
        ("price", D(-1), "price must be positive"),
        ("stop_loss_percent", D(0), "stop loss percent"),
        ("risk_percent", D(0), "risk percent"),
    ],
)
def test_invalid_inputs_raise(field: str, value: D, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        size(**{field: value})


def test_everything_stays_decimal() -> None:
    result = size()
    assert isinstance(result.quantity, D)  # type: ignore[attr-defined]
    assert isinstance(result.notional, D)  # type: ignore[attr-defined]
