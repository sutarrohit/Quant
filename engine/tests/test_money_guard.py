"""The FOUND-09 build-failing guard: a float reaching a money field must fail loudly.

Covers both boundaries money.py keeps separate (see money.py's module docstring): the wire
contract (`parse_money`, a decimal string in) and the internal contract (`Money`, strict
`Decimal` only). Run in the default suite -- never skipped or xfail'd.
"""

from decimal import ROUND_HALF_EVEN, Decimal

import pytest
from pydantic import ValidationError

from money import MONEY_SCALE, Money, assert_no_floats, parse_money, to_canonical_str


# Test 1 (internal contract): a raw float raises, naming the decimal type.
def test_money_rejects_float():
    with pytest.raises(ValidationError, match="Decimal"):
        Money(amount=1.5)


# Test 2 (internal contract): a Decimal instance succeeds.
def test_money_accepts_decimal():
    assert Money(amount=Decimal("1.5")).amount == Decimal("1.5")


# Test 3 (internal contract): strict mode means strict -- a decimal string does not cross the
# internal boundary unparsed, even though it's a valid wire representation.
def test_money_rejects_string_in_python_mode():
    with pytest.raises(ValidationError, match="Decimal"):
        Money(amount="1.50")


# Test 3b (wire contract): parse_money is the one sanctioned route from string to Decimal, and
# feeding its output into Money succeeds -- together with Test 3, this makes the boundary
# visible rather than accidental.
def test_parse_money_then_money_succeeds():
    assert Money(amount=parse_money("1.50")).amount == Decimal("1.50")


# Test 4 (boundary): exactly MONEY_SCALE decimal places is accepted; one more is rejected, not
# silently truncated.
def test_parse_money_accepts_max_scale_rejects_one_more():
    ok = "1." + "1" * MONEY_SCALE
    too_many = "1." + "1" * (MONEY_SCALE + 1)
    assert parse_money(ok) == Decimal(ok)
    with pytest.raises(ValueError):
        parse_money(too_many)


# Test 5 (adjacency): "1.50" and "1.5" compare equal as Decimal and canonicalize identically.
def test_parse_money_adjacency_and_canonical_form():
    assert parse_money("1.50") == parse_money("1.5")
    assert to_canonical_str(parse_money("1.50")) == to_canonical_str(parse_money("1.5"))


# Test 6 (empty): "", None, and an absent Money field each raise -- none becomes Decimal("0").
def test_parse_money_rejects_empty_and_none():
    with pytest.raises(ValueError):
        parse_money("")
    with pytest.raises(TypeError):
        parse_money(None)


def test_money_rejects_absent_field():
    with pytest.raises(ValidationError):
        Money()


# Test 7 (precision): banker's rounding is explicit, not inherited from the ambient context.
def test_to_canonical_str_uses_banker_rounding():
    assert Decimal("2.5").quantize(Decimal(1), rounding=ROUND_HALF_EVEN) == Decimal("2")
    assert Decimal("3.5").quantize(Decimal(1), rounding=ROUND_HALF_EVEN) == Decimal("4")


# Test 8 (leak): a structure built entirely from to_canonical_str output carries no float; the
# walker catches one that does.
def test_assert_no_floats_walker():
    clean = {"trade_size": to_canonical_str(Decimal("1.5")), "legs": [{"qty": "2.0"}]}
    assert_no_floats(clean)  # does not raise

    dirty = {"trade_size": to_canonical_str(Decimal("1.5")), "legs": [{"qty": 2.0}]}
    with pytest.raises(TypeError, match="float"):
        assert_no_floats(dirty)
