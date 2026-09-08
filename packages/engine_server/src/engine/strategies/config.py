"""The shared ``ImportableStrategyConfig`` construction (spec section 10.2).

Both ``backtest/builder.py`` and Phase 5's ``live/node.py`` call this one
function. The spec is explicit about why: the config the live node builds must
be **byte-identical in shape** to the one a backtest builds -- same
``strategy_path``, same ``spec``, same ``spec_hash``. If the two ever construct
it separately they will drift, and the platform's core guarantee, that
simulation and production run the same code path, is gone.

There is nothing else in this module on purpose. It is small so that it stays
the only place.
"""

from __future__ import annotations

from typing import Any

from nautilus_trader.config import ImportableStrategyConfig

#: These strings end up inside stored configs, so renaming the package or the
#: class is a data migration, not a refactor.
STRATEGY_PATH = "engine.strategies.dsl_strategy:DslStrategy"
CONFIG_PATH = "engine.strategies.dsl_strategy:DslStrategyConfig"


def strategy_config(
    *,
    instrument_id: str,
    bar_type: str,
    spec: dict[str, Any],
    strategy_version_id: str,
    spec_hash: str,
    cost_bps: str = "0",
) -> ImportableStrategyConfig:
    return ImportableStrategyConfig(
        strategy_path=STRATEGY_PATH,
        config_path=CONFIG_PATH,
        config={
            "instrument_id": instrument_id,
            "bar_type": bar_type,
            "spec": spec,
            "strategy_version_id": strategy_version_id,
            "spec_hash": spec_hash,
            "cost_bps": cost_bps,
        },
    )
