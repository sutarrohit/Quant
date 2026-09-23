"""Strategy spec schema (spec section 5.1).

Every model here is ``frozen=True`` and ``extra="forbid"``. Neither is optional:

* **frozen** -- a spec is hashed into a ``strategy_version_id`` and that hash
  has to keep meaning the same thing. A mutable spec could be edited after
  hashing, and the stored result would then describe a strategy that no longer
  exists.
* **extra="forbid"** -- a typo'd field must be a hard error. ``stopLosPercent``
  silently ignored is a strategy running without a stop, which is exactly the
  failure this platform exists to prevent.

**Numbers.** Everything numeric is ``Decimal`` except ``period`` and
``version``, which are counts. Spec section 5.1 permits ``float`` for indicator
thresholds, but this schema does not use that latitude: floats do not round-trip
through JSON exactly, and a spec whose hash changes when it is re-read is
useless as a version identifier.

**JSON is camelCase, Python is snake_case.** The wire format is fixed by the
TypeScript caller; the alias generator bridges them.

Schema validation is deliberately structural. Semantic rules -- an empty entry
group, an unsupported indicator/operator pairing, a period longer than the
available warmup -- belong to ``dsl/validator.py`` (Step 9), which reports every
problem at once with a path, rather than failing on the first.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal, Self, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    model_validator,
)
from pydantic.alias_generators import to_camel

from engine.data.timeframes import Timeframe

# Bounds the interpreter's cost and stops pathological generated specs
# (spec section 5.1).
MAX_DEPTH = 5
MAX_LEAVES = 32


class Exchange(StrEnum):
    BINANCE = "binance"


class MarketType(StrEnum):
    SPOT = "spot"


class Operator(StrEnum):
    """Comparisons a condition may use.

    Which operators are legal for which indicator is a *semantic* question --
    ``crossesAbove`` on a non-series value is nonsense but not a schema error.
    That pairing check lives in the validator.
    """

    CROSSES_ABOVE = "crossesAbove"
    CROSSES_BELOW = "crossesBelow"
    GREATER_THAN = "greaterThan"
    LESS_THAN = "lessThan"
    GREATER_THAN_SMA = "greaterThanSma"
    LESS_THAN_SMA = "lessThanSma"


class DslModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        alias_generator=to_camel,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# --- market -------------------------------------------------------------


class Market(DslModel):
    exchange: Exchange
    market_type: MarketType
    symbols: list[str] = Field(min_length=1, max_length=8)
    timeframe: Timeframe

    def instrument_id(self, symbol: str) -> str:
        """The Nautilus instrument id for one of this market's symbols.

        Specs write pairs the way people do (``BTC/USDT``); the catalog keys
        them the way the venue does (``BTCUSDT.BINANCE``). Deriving it here
        keeps the validator, the strategy and the backtest builder from each
        inventing their own spelling.
        """
        return f"{symbol.replace('/', '').upper()}.{self.exchange.value.upper()}"

    @property
    def instrument_ids(self) -> tuple[str, ...]:
        return tuple(self.instrument_id(symbol) for symbol in self.symbols)


# --- condition leaves ---------------------------------------------------


class SeriesReference(DslModel):
    """Another series to compare against, instead of a fixed number.

    This is what makes a crossover expressible: ``sma(10) crossesAbove
    sma(50)``, or ``close crossesAbove sma(200)``. Without it the DSL could
    only compare an indicator to a constant, which rules out the entire
    moving-average-crossover family -- the most widely published strategies
    there are.
    """

    indicator: Literal["rsi", "sma", "ema", "atr", "close", "volume"]
    period: int | None = Field(default=None, ge=2, le=1000)


class IndicatorConditionBase(DslModel):
    operator: Operator
    #: A fixed threshold. Mutually exclusive with `reference`; the validator
    #: rejects a condition carrying both or neither.
    value: Decimal | None = None
    #: Another series to compare against.
    reference: SeriesReference | None = None


class RsiCondition(IndicatorConditionBase):
    indicator: Literal["rsi"]
    period: int = Field(ge=2, le=1000)


class SmaCondition(IndicatorConditionBase):
    indicator: Literal["sma"]
    period: int = Field(ge=2, le=1000)


class EmaCondition(IndicatorConditionBase):
    indicator: Literal["ema"]
    period: int = Field(ge=2, le=1000)


class AtrCondition(IndicatorConditionBase):
    indicator: Literal["atr"]
    period: int = Field(ge=2, le=1000)


class VolumeCondition(IndicatorConditionBase):
    """Read from the bar itself rather than from an indicator object.

    ``period`` is the lookback for ``greaterThanSma`` / ``lessThanSma`` and is
    absent for a plain threshold comparison.
    """

    indicator: Literal["volume"]
    period: int | None = Field(default=None, ge=2, le=1000)


class CloseCondition(IndicatorConditionBase):
    """The bar's closing price.

    Has no period of its own. Exists so ``close crossesAbove sma(200)`` can be
    written, which together with `SeriesReference` covers price-versus-average
    strategies.
    """

    indicator: Literal["close"]


IndicatorCondition = Annotated[
    Union[  # noqa: UP007 -- Field(discriminator=...) needs an explicit Union
        RsiCondition,
        SmaCondition,
        EmaCondition,
        AtrCondition,
        VolumeCondition,
        CloseCondition,
    ],
    Field(discriminator="indicator"),
]


class TakeProfitPercent(DslModel):
    type: Literal["takeProfitPercent"]
    value: Decimal = Field(gt=0, le=1000)


class StopLossPercent(DslModel):
    type: Literal["stopLossPercent"]
    value: Decimal = Field(gt=0, lt=100)


ExitCondition = Annotated[
    Union[TakeProfitPercent, StopLossPercent],  # noqa: UP007
    Field(discriminator="type"),
]


# --- groups -------------------------------------------------------------
#
# `not` is a keyword and `all`/`any` are builtins, so the Python attributes are
# suffixed and the JSON names come from explicit aliases.


class AllGroup(DslModel):
    all_: list[ConditionNode] = Field(alias="all")


class AnyGroup(DslModel):
    any_: list[ConditionNode] = Field(alias="any")


class NotGroup(DslModel):
    not_: ConditionNode = Field(alias="not")


def _node_tag(value: Any) -> str | None:
    """Pick the node kind from the key that is present.

    Groups and leaves are told apart by shape rather than by a shared
    discriminator field, because that is the JSON shape the spec fixes.
    Returning ``None`` produces a "unable to extract tag" error rather than a
    confusing cascade of union failures.
    """
    if isinstance(value, dict):
        for key in ("all", "any", "not", "indicator", "type"):
            if key in value:
                return key
        # Accept Python-side names too, so a round-tripped model re-validates.
        for attribute, key in (("all_", "all"), ("any_", "any"), ("not_", "not")):
            if attribute in value:
                return key
        return None

    for attribute, key in (("all_", "all"), ("any_", "any"), ("not_", "not")):
        if hasattr(value, attribute):
            return key
    if hasattr(value, "indicator"):
        return "indicator"
    if hasattr(value, "type"):
        return "type"
    return None


ConditionNode = Annotated[
    Union[  # noqa: UP007
        Annotated[AllGroup, Tag("all")],
        Annotated[AnyGroup, Tag("any")],
        Annotated[NotGroup, Tag("not")],
        Annotated[IndicatorCondition, Tag("indicator")],
        Annotated[ExitCondition, Tag("type")],
    ],
    Discriminator(_node_tag),
]

AllGroup.model_rebuild()
AnyGroup.model_rebuild()
NotGroup.model_rebuild()


def walk(node: object) -> tuple[int, int]:
    """Return ``(depth, leaf_count)`` for a condition tree."""
    if isinstance(node, AllGroup):
        children = list(node.all_)
    elif isinstance(node, AnyGroup):
        children = list(node.any_)
    elif isinstance(node, NotGroup):
        children = [node.not_]
    else:
        return 1, 1

    if not children:
        return 1, 0
    results = [walk(child) for child in children]
    return 1 + max(depth for depth, _ in results), sum(leaves for _, leaves in results)


# --- sizing -------------------------------------------------------------


class RiskPercentSizing(DslModel):
    """Size from the risk budget: equity x riskPercent, divided by stop distance."""

    type: Literal["riskPercent"]
    risk_percent: Decimal = Field(gt=0, le=100)


Sizing = Annotated[RiskPercentSizing, Field(discriminator="type")]


# --- the spec -----------------------------------------------------------


class StrategySpec(DslModel):
    strategy_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
    version: int = Field(ge=1)
    market: Market
    entry: ConditionNode
    # `exit` shadows a builtin; the JSON name is unaffected.
    exit_: ConditionNode = Field(alias="exit")
    sizing: Sizing

    @model_validator(mode="after")
    def _within_complexity_limits(self) -> Self:
        for name, node in (("entry", self.entry), ("exit", self.exit_)):
            depth, leaves = walk(node)
            if depth > MAX_DEPTH:
                raise ValueError(f"{name} nests {depth} levels deep, the limit is {MAX_DEPTH}")
            if leaves > MAX_LEAVES:
                raise ValueError(f"{name} has {leaves} conditions, the limit is {MAX_LEAVES}")
        return self


__all__ = [
    "MAX_DEPTH",
    "MAX_LEAVES",
    "AllGroup",
    "AnyGroup",
    "AtrCondition",
    "CloseCondition",
    "ConditionNode",
    "EmaCondition",
    "Exchange",
    "Market",
    "MarketType",
    "NotGroup",
    "Operator",
    "RiskPercentSizing",
    "RsiCondition",
    "SeriesReference",
    "SmaCondition",
    "StopLossPercent",
    "StrategySpec",
    "TakeProfitPercent",
    "Timeframe",
    "VolumeCondition",
    "walk",
]
