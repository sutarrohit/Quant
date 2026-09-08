from __future__ import annotations

import pytest
from nautilus_trader.model import BarType

from engine.data.timeframes import Timeframe


def test_the_enum_is_closed() -> None:
    # Spec section 5.1: adding a timeframe must be deliberate.
    assert [tf.value for tf in Timeframe] == ["1m", "5m", "15m", "1h", "4h", "1d"]


@pytest.mark.parametrize(
    ("timeframe", "milliseconds"),
    [
        (Timeframe.M1, 60_000),
        (Timeframe.M5, 300_000),
        (Timeframe.M15, 900_000),
        (Timeframe.H1, 3_600_000),
        (Timeframe.H4, 14_400_000),
        (Timeframe.D1, 86_400_000),
    ],
)
def test_milliseconds(timeframe: Timeframe, milliseconds: int) -> None:
    assert timeframe.milliseconds == milliseconds


def test_nanoseconds_are_milliseconds_scaled() -> None:
    for timeframe in Timeframe:
        assert timeframe.nanoseconds == timeframe.milliseconds * 1_000_000


def test_every_aggregation_builds_a_real_bar_type() -> None:
    # A wrong aggregation string would fail deep inside Nautilus at backtest
    # time rather than here.
    for timeframe in Timeframe:
        bar_type = BarType.from_str(f"BTCUSDT.BINANCE-{timeframe.aggregation}-LAST-EXTERNAL")
        assert str(bar_type).endswith(f"{timeframe.aggregation}-LAST-EXTERNAL")


def test_every_member_has_a_duration_and_an_aggregation() -> None:
    for timeframe in Timeframe:
        assert timeframe.duration.total_seconds() > 0
        assert timeframe.aggregation


def test_is_a_string_enum() -> None:
    assert Timeframe("15m") is Timeframe.M15
    assert f"{Timeframe.M15}" == "15m"
