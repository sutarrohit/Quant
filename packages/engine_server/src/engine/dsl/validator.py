"""Semantic validation (spec section 5.2).

Schema validity is not enough. A spec can parse cleanly and still be
unrunnable: an indicator paired with an operator that means nothing for it, a
period longer than the data, a risk-sized strategy with no stop to divide by.

**Every problem is reported, not the first.** A caller fixing one field per
round trip is a bad API, and the TypeScript side wants the whole list to show a
user at once. Each error carries a JSON path, so it can be pointed at the exact
field.

Most checks are pure. The symbol check needs to know what the catalog holds, so
it is injected -- pass ``known_instruments`` to enable it, omit it and that one
check is skipped. Nothing else here touches the world.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator

from engine.dsl.indicators import supported_operators, warmup_bars
from engine.dsl.keys import BAR_DERIVED, PERIODIC, SMA_OPERATORS, required_refs
from engine.errors import UnknownIndicatorError
from engine.types.dsl import (
    AllGroup,
    AnyGroup,
    NotGroup,
    Operator,
    RiskPercentSizing,
    StopLossPercent,
    StrategySpec,
    TakeProfitPercent,
)
from engine.types.spec_errors import SpecError, SpecErrorCode


def walk(node: object, path: str) -> Iterator[tuple[str, object]]:
    """Yield every node with the JSON path that reaches it."""
    yield path, node
    if isinstance(node, AllGroup):
        for index, child in enumerate(node.all_):
            yield from walk(child, f"{path}.all[{index}]")
    elif isinstance(node, AnyGroup):
        for index, child in enumerate(node.any_):
            yield from walk(child, f"{path}.any[{index}]")
    elif isinstance(node, NotGroup):
        yield from walk(node.not_, f"{path}.not")


def _is_exit_condition(node: object) -> bool:
    return isinstance(node, TakeProfitPercent | StopLossPercent)


def _is_indicator_condition(node: object) -> bool:
    return hasattr(node, "indicator") and hasattr(node, "operator")


def _check_condition(node: object, path: str) -> Iterator[SpecError]:
    indicator: str = node.indicator  # type: ignore[attr-defined]
    operator: Operator = node.operator  # type: ignore[attr-defined]
    period: int | None = getattr(node, "period", None)

    try:
        allowed = supported_operators(indicator)
    except UnknownIndicatorError:
        # Unreachable through the schema's discriminated union, but the
        # validator is also called on hand-built specs in tests and by the
        # worker, so it does not assume.
        yield SpecError(
            path=f"{path}.indicator",
            code=SpecErrorCode.UNKNOWN_INDICATOR,
            message=f"unknown indicator {indicator!r}",
            observed=indicator,
        )
        return

    if operator not in allowed:
        yield SpecError(
            path=f"{path}.operator",
            code=SpecErrorCode.UNSUPPORTED_OPERATOR,
            message=(
                f"{indicator!r} does not support {operator.value!r}; "
                f"supported: {', '.join(sorted(op.value for op in allowed))}"
            ),
            observed=operator.value,
            limit=", ".join(sorted(op.value for op in allowed)),
        )
        return

    threshold = getattr(node, "value", None)
    reference = getattr(node, "reference", None)

    if threshold is not None and reference is not None:
        yield SpecError(
            path=path,
            code=SpecErrorCode.AMBIGUOUS_COMPARISON,
            message="a condition compares against either a value or a reference series, not both",
        )
        return

    if reference is not None:
        yield from _check_reference(reference, f"{path}.reference")
        if operator in SMA_OPERATORS:
            yield SpecError(
                path=f"{path}.operator",
                code=SpecErrorCode.AMBIGUOUS_COMPARISON,
                message=(
                    f"{operator.value!r} already compares against a moving average, "
                    "so it cannot also take a reference series"
                ),
            )
        return

    if operator in SMA_OPERATORS and period is None:
        yield SpecError(
            path=f"{path}.period",
            code=SpecErrorCode.MISSING_PERIOD,
            message=f"{operator.value!r} averages over a window, so it needs a period",
        )
    elif operator not in SMA_OPERATORS and threshold is None:
        yield SpecError(
            path=f"{path}.value",
            code=SpecErrorCode.MISSING_THRESHOLD,
            message=(
                f"{operator.value!r} compares against something, and neither a `value` nor a `reference` was given"
            ),
        )


def _check_reference(reference: object, path: str) -> Iterator[SpecError]:
    """A reference series must itself be buildable."""
    name: str = reference.indicator  # type: ignore[attr-defined]
    period: int | None = reference.period  # type: ignore[attr-defined]

    if name in PERIODIC and period is None:
        yield SpecError(
            path=f"{path}.period",
            code=SpecErrorCode.INVALID_REFERENCE,
            message=f"{name!r} needs a period",
        )
    elif name in BAR_DERIVED and period is not None:
        yield SpecError(
            path=f"{path}.period",
            code=SpecErrorCode.INVALID_REFERENCE,
            message=f"{name!r} is read from the bar and has no period",
            observed=str(period),
        )


def _check_warmup(spec: StrategySpec, available_bars: int) -> Iterator[SpecError]:
    """Warmup for every series the spec implies.

    Conditions already reported as malformed are skipped rather than probed. An
    unsupported pairing like ``atr`` + ``greaterThanSma`` implies an ``atrSma``
    series that the registry has no entry for, and asking for its warmup would
    make the validator *raise* -- a 500 where the caller should get a 422 and a
    list.
    """
    for _, (path, condition) in _conditions(spec):
        if not _is_indicator_condition(condition):
            continue
        try:
            reference = getattr(condition, "reference", None)
            refs = required_refs(
                condition.indicator,  # type: ignore[attr-defined]
                condition.operator,  # type: ignore[attr-defined]
                getattr(condition, "period", None),
                (reference.indicator, reference.period) if reference is not None else None,
            )
            needed_by_ref = [(ref, warmup_bars(ref.name, ref.period)) for ref in refs]
        except UnknownIndicatorError:
            continue
        for ref, needed in needed_by_ref:
            if needed > available_bars:
                yield SpecError(
                    path=f"{path}.period",
                    code=SpecErrorCode.INDICATOR_PERIOD_TOO_LARGE,
                    message=(
                        f"{ref.name} needs {needed} bars to warm up but the window "
                        f"holds {available_bars}; it would never produce a signal"
                    ),
                    limit=str(available_bars),
                    observed=str(needed),
                )


def _conditions(spec: StrategySpec) -> Iterator[tuple[str, tuple[str, object]]]:
    for root, node in (("entry", spec.entry), ("exit", spec.exit_)):
        for path, child in walk(node, root):
            yield root, (path, child)


def validate_spec(
    spec: StrategySpec,
    *,
    available_bars: int | None = None,
    known_instruments: Collection[str] | None = None,
) -> list[SpecError]:
    """Every semantic problem with a spec, in document order.

    ``available_bars`` enables the warmup check; ``known_instruments`` enables
    the catalog check. Both are optional so the pure checks stay usable without
    a catalog or a backtest window.
    """
    errors: list[SpecError] = []
    seen: dict[str, set[str]] = {"entry": set(), "exit": set()}

    for root, (path, node) in _conditions(spec):
        if isinstance(node, AllGroup | AnyGroup):
            children = node.all_ if isinstance(node, AllGroup) else node.any_
            if not children:
                errors.append(
                    SpecError(
                        path=path,
                        code=SpecErrorCode.EMPTY_CONDITION_GROUP,
                        message=(
                            "an empty group has no meaning: `all` of nothing is true, which would fire on every bar"
                        ),
                    )
                )
            continue

        if isinstance(node, NotGroup):
            continue

        if _is_exit_condition(node):
            if root == "entry":
                errors.append(
                    SpecError(
                        path=path,
                        code=SpecErrorCode.EXIT_CONDITION_IN_ENTRY,
                        message=(
                            f"{type(node).__name__} measures a position's PnL, so it "
                            "cannot be an entry condition -- there is no position yet"
                        ),
                    )
                )
            continue

        if _is_indicator_condition(node):
            errors.extend(_check_condition(node, path))
            fingerprint = node.model_dump_json()  # type: ignore[attr-defined]
            if fingerprint in seen[root]:
                errors.append(
                    SpecError(
                        path=path,
                        code=SpecErrorCode.DUPLICATE_CONDITION,
                        message="this condition is stated twice in the same tree",
                    )
                )
            seen[root].add(fingerprint)

    if isinstance(spec.sizing, RiskPercentSizing) and not _has_stop_loss(spec):
        errors.append(
            SpecError(
                path="exit",
                code=SpecErrorCode.MISSING_STOP_LOSS,
                message=(
                    "riskPercent sizing divides the risk budget by the stop distance, "
                    "so a stopLossPercent exit condition is required"
                ),
            )
        )

    if available_bars is not None:
        errors.extend(_check_warmup(spec, available_bars))

    if known_instruments is not None:
        known = set(known_instruments)
        for index, symbol in enumerate(spec.market.symbols):
            instrument_id = spec.market.instrument_id(symbol)
            if instrument_id not in known:
                errors.append(
                    SpecError(
                        path=f"market.symbols[{index}]",
                        code=SpecErrorCode.SYMBOL_NOT_IN_CATALOG,
                        message=(f"{instrument_id} is not in the catalog and is not listed at the venue"),
                        observed=instrument_id,
                    )
                )

    return errors


def _has_stop_loss(spec: StrategySpec) -> bool:
    """A stop in the *exit* tree. One in `entry` is already an error of its own."""
    return any(isinstance(node, StopLossPercent) for _, node in walk(spec.exit_, "exit"))
