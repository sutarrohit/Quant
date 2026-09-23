"""Turn a validated request into a ``BacktestRunConfig`` (spec section 7.3).

A pure function. Same request and spec in, same config out -- no clock, no
Redis, no filesystem -- so the assembly that decides what a backtest actually
simulates is unit-testable and golden-file comparable.

Two things this module refuses to do: **default a cost to zero** (fees and
slippage are required, so an omission is a 422 before reaching here), and
**configure a cache database** (a write per event for no benefit, and shared
mutable state breaks determinism -- ``assert_no_cache_database`` enforces it).
"""

from __future__ import annotations

from nautilus_trader.backtest.config import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestRunConfig,
    BacktestVenueConfig,
)
from nautilus_trader.config import ImportableFeeModelConfig, LoggingConfig
from nautilus_trader.model import Bar

from engine.dsl.hashing import spec_hash
from engine.errors import BacktestConfigError
from engine.settings import Settings
from engine.strategies.config import strategy_config
from engine.types.backtest import BacktestRequest
from engine.types.dsl import StrategySpec

FEE_MODEL_PATH = "engine.backtest.fees:BpsFeeModel"
FEE_CONFIG_PATH = "engine.backtest.fees:BpsFeeModelConfig"


def assert_no_cache_database(config: BacktestRunConfig) -> None:
    """Fail fast if a backtest was handed a cache database.

    Spec section 9.2 and section 13 pitfall 10. Two runs sharing an external
    cache no longer share only their inputs, and the determinism test in
    section 12 stops meaning anything.
    """
    cache = getattr(config.engine, "cache", None)
    if cache is not None and getattr(cache, "database", None) is not None:
        raise BacktestConfigError(
            "a backtest must use the in-memory cache; a cache database adds "
            "shared mutable state and breaks determinism",
        )


def build_venue_config(request: BacktestRequest) -> BacktestVenueConfig:
    return BacktestVenueConfig(
        name=request.venue,
        oms_type="NETTING",
        account_type="CASH",
        base_currency=None,
        starting_balances=list(request.starting_balances),
        fee_model=ImportableFeeModelConfig(
            fee_model_path=FEE_MODEL_PATH,
            config_path=FEE_CONFIG_PATH,
            # Strings all the way through: these multiply every notional in
            # the result.
            config={
                "maker_bps": str(request.fees.maker_bps),
                "taker_bps": str(request.fees.taker_bps),
                "slippage_bps": str(request.slippage_bps),
            },
        ),
    )


def build_data_config(request: BacktestRequest, settings: Settings) -> BacktestDataConfig:
    return BacktestDataConfig(
        catalog_path=settings.catalog_path,
        data_cls=Bar,
        instrument_id=request.instrument_id,
        bar_types=[request.bar_type],
        start_time=request.start.isoformat(),
        end_time=request.end.isoformat(),
    )


def build_run_config(
    request: BacktestRequest,
    spec: StrategySpec,
    settings: Settings,
) -> BacktestRunConfig:
    """``(request, spec) -> BacktestRunConfig``. No side effects."""
    engine = BacktestEngineConfig(
        strategies=[
            strategy_config(
                instrument_id=request.instrument_id,
                bar_type=request.bar_type,
                spec=spec.model_dump(mode="json", by_alias=True),
                strategy_version_id=request.strategy_version_id,
                spec_hash=spec_hash(spec),
                # Sizing must leave room for the commission it will pay.
                cost_bps=str(request.fees.taker_bps + request.slippage_bps),
            )
        ],
        logging=LoggingConfig(log_level=settings.log_level),
    )

    config = BacktestRunConfig(
        engine=engine,
        venues=[build_venue_config(request)],
        data=[build_data_config(request, settings)],
        # Reports are read from the engine after the run, so it cannot be
        # disposed on completion. The runner disposes it explicitly once the
        # results are out (spec section 7.4, and D9).
        dispose_on_completion=False,
    )
    assert_no_cache_database(config)
    return config
