from __future__ import annotations

import pytest
from nautilus_trader.model import Bar, BarType, Price, Quantity

from engine.dsl.indicators import (
    DERIVED,
    INDICATORS,
    SERIES_OPERATORS,
    VOLUME_OPERATORS,
    Series,
    build,
    build_series,
    required_series,
    supported_operators,
    warmup_bars,
)
from engine.dsl.keys import SeriesRef, series_key
from engine.dsl.schema import Operator
from engine.errors import UnknownIndicatorError

BAR_TYPE = BarType.from_str("BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL")
STEP_NS = 900_000_000_000

# Every indicator a spec may name. A new registry entry must be added here too,
# which is what makes "one entry plus one test" enforceable rather than a wish.
NAMES = ["rsi", "sma", "ema", "atr", "volume", "close"]
PERIODIC = ["rsi", "sma", "ema", "atr"]


def bar(index: int, *, volume: str = "1.50000") -> Bar:
    price = 40000 + index * 7
    return Bar(
        bar_type=BAR_TYPE,
        open=Price.from_str(f"{price}.00"),
        high=Price.from_str(f"{price + 10}.00"),
        low=Price.from_str(f"{price - 10}.00"),
        close=Price.from_str(f"{price + 5}.00"),
        volume=Quantity.from_str(volume),
        ts_event=STEP_NS * (100 + index),
        ts_init=STEP_NS * (100 + index),
    )


def feed(series: Series, count: int, **kwargs: str) -> Series:
    for index in range(count):
        series.handle_bar(bar(index, **kwargs))
    return series


# --- registry completeness ----------------------------------------------


def test_registry_holds_exactly_the_documented_indicators() -> None:
    assert sorted(INDICATORS) == sorted(NAMES)


def test_derived_series_are_not_spec_addressable() -> None:
    # A spec can never name volumeSma: the schema's discriminated union has no
    # member for it, so it is unreachable from user input by construction.
    assert set(DERIVED) == {"volumeSma"}
    assert set(DERIVED).isdisjoint(INDICATORS)


@pytest.mark.parametrize("name", NAMES)
def test_every_entry_declares_its_operators(name: str) -> None:
    assert supported_operators(name)


# --- construction and warmup --------------------------------------------


@pytest.mark.parametrize("name", PERIODIC)
def test_periodic_indicators_initialize_after_exactly_period_bars(name: str) -> None:
    period = 5
    series = build_series(name, period)

    feed(series, period - 1)
    assert series.initialized is False, f"{name} warmed up early"

    series.handle_bar(bar(period - 1))
    assert series.initialized is True
    assert warmup_bars(name, period) == period


@pytest.mark.parametrize("name", PERIODIC)
def test_periodic_indicators_produce_a_number(name: str) -> None:
    series = feed(build_series(name, 5), 20)
    assert isinstance(series.value, float)


@pytest.mark.parametrize("name", PERIODIC)
def test_periodic_indicators_require_a_period(name: str) -> None:
    with pytest.raises(UnknownIndicatorError, match="requires a period"):
        build_series(name, None)


def test_volume_is_ready_from_the_first_bar() -> None:
    series = build_series("volume", None)
    assert series.initialized is False
    series.handle_bar(bar(0, volume="12.34000"))
    assert series.initialized is True
    assert series.value == pytest.approx(12.34)
    assert warmup_bars("volume", None) == 1


def test_volume_tracks_the_current_bar() -> None:
    series = build_series("volume", None)
    series.handle_bar(bar(0, volume="1.00000"))
    series.handle_bar(bar(1, volume="9.00000"))
    assert series.value == pytest.approx(9.0)


def test_volume_sma_averages_volume_not_price() -> None:
    # A plain SimpleMovingAverage fed bars would average the close. If this
    # ever regresses, the value lands near 40000 instead of near 2.
    series = build_series("volumeSma", 3)
    for volume in ("1.00000", "2.00000", "3.00000"):
        series.handle_bar(bar(0, volume=volume))
    assert series.initialized is True
    assert series.value == pytest.approx(2.0)


def test_volume_sma_warms_up_over_its_period() -> None:
    series = build_series("volumeSma", 4)
    feed(series, 3)
    assert series.initialized is False
    series.handle_bar(bar(3))
    assert series.initialized is True
    assert warmup_bars("volumeSma", 4) == 4


# --- unknown names raise -------------------------------------------------


@pytest.mark.parametrize("name", ["macd", "bollinger", "", "RSI"])
def test_unknown_indicator_raises(name: str) -> None:
    # Never a default, never a silent False: that turns a broken strategy into
    # a silently inert one (spec section 13, pitfall 9).
    with pytest.raises(UnknownIndicatorError, match="unknown indicator"):
        build_series(name, 14)
    with pytest.raises(UnknownIndicatorError):
        warmup_bars(name, 14)
    with pytest.raises(UnknownIndicatorError):
        supported_operators(name)


# --- operator sets -------------------------------------------------------


@pytest.mark.parametrize("name", PERIODIC)
def test_series_indicators_support_crossings(name: str) -> None:
    assert supported_operators(name) == SERIES_OPERATORS
    assert Operator.CROSSES_ABOVE in supported_operators(name)


def test_volume_supports_sma_comparison_not_crossings() -> None:
    assert supported_operators("volume") == VOLUME_OPERATORS
    assert Operator.GREATER_THAN_SMA in supported_operators("volume")
    assert Operator.CROSSES_ABOVE not in supported_operators("volume")


def test_sma_comparison_is_volume_only() -> None:
    # `period` is already the indicator's own period on rsi/sma/ema/atr, so
    # greaterThanSma there would need a second one. Left out deliberately;
    # the validator rejects the pairing in Step 9.
    for name in PERIODIC:
        assert Operator.GREATER_THAN_SMA not in supported_operators(name)


# --- series keys and requests -------------------------------------------


def test_series_key_includes_the_period() -> None:
    assert series_key("rsi", 14) == "rsi:14"
    assert series_key("volume", None) == "volume"


def test_identical_conditions_share_one_series() -> None:
    # Two conditions naming rsi(14) must not compute the same numbers twice.
    first = required_series("rsi", Operator.GREATER_THAN, 14)
    second = required_series("rsi", Operator.CROSSES_ABOVE, 14)
    assert first[0].key == second[0].key == "rsi:14"


def test_different_periods_are_different_series() -> None:
    assert required_series("rsi", Operator.GREATER_THAN, 14)[0].key != (
        required_series("rsi", Operator.GREATER_THAN, 21)[0].key
    )


def test_a_plain_comparison_needs_one_series() -> None:
    requests = required_series("rsi", Operator.GREATER_THAN, 14)
    assert requests == (SeriesRef("rsi:14", "rsi", 14),)


def test_sma_comparison_needs_the_subject_and_its_average() -> None:
    requests = required_series("volume", Operator.GREATER_THAN_SMA, 20)
    assert [request.key for request in requests] == ["volume", "volumeSma:20"]
    assert requests[0].period is None  # volume itself has no period
    assert requests[1].period == 20  # 20 is the averaging window


def test_volume_period_is_the_averaging_window_not_its_own() -> None:
    plain = required_series("volume", Operator.GREATER_THAN, None)
    assert plain == (SeriesRef("volume", "volume", None),)


def test_sma_comparison_without_a_period_raises() -> None:
    with pytest.raises(UnknownIndicatorError, match="requires a period"):
        required_series("volume", Operator.GREATER_THAN_SMA, None)


def test_required_series_rejects_an_unknown_indicator() -> None:
    with pytest.raises(UnknownIndicatorError, match="unknown indicator"):
        required_series("macd", Operator.GREATER_THAN, 14)


def test_refs_build_and_report_warmup() -> None:
    ref = required_series("rsi", Operator.GREATER_THAN, 9)[0]
    assert warmup_bars(ref.name, ref.period) == 9
    assert feed(build(ref), 9).initialized is True


def test_keys_module_stays_pure() -> None:
    # keys.py exists so the interpreter can derive series names without
    # importing Nautilus. If it ever gains a Nautilus import, that split is
    # gone and interpreter purity goes with it.
    import ast
    from pathlib import Path

    tree = ast.parse(Path("src/engine/dsl/keys.py").read_text())
    modules = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "nautilus_trader" not in modules


def test_both_modules_derive_keys_from_one_place() -> None:
    # The strategy builds a series and the interpreter reads it; they must
    # agree on its name.
    from engine.dsl import keys

    ref = required_series("volume", Operator.GREATER_THAN_SMA, 20)[1]
    assert ref.key == keys.series_key("volumeSma", 20)
