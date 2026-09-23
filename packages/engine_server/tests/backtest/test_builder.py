from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from engine.backtest.builder import assert_no_cache_database, build_run_config
from engine.dsl.hashing import spec_hash
from engine.errors import BacktestConfigError
from engine.settings import Settings
from engine.strategies.config import CONFIG_PATH, STRATEGY_PATH, strategy_config
from engine.types.backtest import BacktestRequest
from engine.types.dsl import StrategySpec

GOLDEN = Path("tests/fixtures/backtest_run_config.golden.json")

#: A request whose window the Phase 0 catalog actually covers.
from tests.backtest.conftest import REQUEST as REQUEST_FOR_RUN  # noqa: E402


def build(request: BacktestRequest, settings: Settings) -> Any:
    return build_run_config(request, StrategySpec.model_validate(request.spec), settings)


def summarise(config: Any) -> dict[str, Any]:
    """The parts of a run config that decide what is simulated."""
    venue = config.venues[0]
    data = config.data[0]
    strategy = config.engine.strategies[0]
    return {
        "venue": {
            "name": venue.name,
            "oms_type": str(venue.oms_type),
            "account_type": str(venue.account_type),
            "base_currency": venue.base_currency,
            "starting_balances": list(venue.starting_balances),
            "fee_model": {
                "fee_model_path": venue.fee_model.fee_model_path,
                "config_path": venue.fee_model.config_path,
                "config": dict(venue.fee_model.config),
            },
        },
        "data": {
            "catalog_path": data.catalog_path,
            "instrument_id": data.instrument_id,
            "bar_types": list(data.bar_types),
            "start_time": str(data.start_time),
            "end_time": str(data.end_time),
        },
        "strategy": {
            "strategy_path": strategy.strategy_path,
            "config_path": strategy.config_path,
            "config": strategy.config,
        },
        "dispose_on_completion": config.dispose_on_completion,
    }


# --- purity --------------------------------------------------------------


def test_the_builder_is_pure(backtest_request: BacktestRequest, builder_settings: Settings) -> None:
    # Same inputs, same config. No clock, no Redis, no filesystem.
    first = summarise(build(backtest_request, builder_settings))
    second = summarise(build(backtest_request, builder_settings))
    assert first == second


# --- golden file ---------------------------------------------------------


def test_matches_the_golden_config(backtest_request: BacktestRequest, builder_settings: Settings) -> None:
    """A diff here means the simulated conditions changed.

    That must be a deliberate act, not a side effect: every stored result was
    produced under the config this file records.
    """
    produced = summarise(build(backtest_request, builder_settings))

    if not GOLDEN.exists():  # pragma: no cover - first run only
        GOLDEN.write_text(json.dumps(produced, indent=2, sort_keys=True) + "\n")
        pytest.fail(f"wrote a new golden file at {GOLDEN}; review and re-run")

    assert produced == json.loads(GOLDEN.read_text())


# --- costs ---------------------------------------------------------------


def test_fees_and_slippage_reach_the_fee_model(backtest_request: BacktestRequest, builder_settings: Settings) -> None:
    fee_model = build(backtest_request, builder_settings).venues[0].fee_model
    assert fee_model.fee_model_path == "engine.backtest.fees:BpsFeeModel"
    assert fee_model.config == {"maker_bps": "1", "taker_bps": "10", "slippage_bps": "5"}


def test_costs_are_carried_as_strings(request_dict: dict[str, Any], builder_settings: Settings) -> None:
    # Floats would compound a rounding error across every notional.
    request_dict["fees"]["takerBps"] = "7.5"
    config = build(BacktestRequest.model_validate(request_dict), builder_settings)
    assert config.venues[0].fee_model.config["taker_bps"] == "7.5"
    assert all(isinstance(v, str) for v in config.venues[0].fee_model.config.values())


def test_a_fee_model_is_always_configured(request_dict: dict[str, Any], builder_settings: Settings) -> None:
    # Even at zero: an unset fee model and an explicit zero look the same in a
    # result, and only one of them was a decision.
    request_dict["fees"] = {"makerBps": "0", "takerBps": "0"}
    request_dict["slippageBps"] = "0"
    config = build(BacktestRequest.model_validate(request_dict), builder_settings)
    assert config.venues[0].fee_model is not None


# --- no cache database ---------------------------------------------------


def test_backtests_get_no_cache_database(backtest_request: BacktestRequest, builder_settings: Settings) -> None:
    # Spec section 9.2: a cache DB adds a write per event and introduces shared
    # mutable state, which breaks the determinism guarantee.
    config = build(backtest_request, builder_settings)
    cache = getattr(config.engine, "cache", None)
    assert cache is None or getattr(cache, "database", None) is None


def test_a_cache_database_fails_fast() -> None:
    from nautilus_trader.backtest.config import BacktestEngineConfig, BacktestRunConfig
    from nautilus_trader.config import CacheConfig, DatabaseConfig

    config = BacktestRunConfig(
        engine=BacktestEngineConfig(
            cache=CacheConfig(database=DatabaseConfig(type="redis", host="localhost", port=6379))
        ),
        venues=[],
        data=[],
    )
    with pytest.raises(BacktestConfigError, match="in-memory cache"):
        assert_no_cache_database(config)


def test_an_in_memory_cache_is_accepted() -> None:
    from nautilus_trader.backtest.config import BacktestEngineConfig, BacktestRunConfig
    from nautilus_trader.config import CacheConfig

    config = BacktestRunConfig(engine=BacktestEngineConfig(cache=CacheConfig()), venues=[], data=[])
    assert_no_cache_database(config)


# --- the shared strategy config ------------------------------------------


def test_the_strategy_config_comes_from_the_shared_factory(
    backtest_request: BacktestRequest, builder_settings: Settings
) -> None:
    """Spec section 10.2: live must build this identically.

    If the builder ever constructs it inline, this fails -- which is the point.
    """
    spec = StrategySpec.model_validate(backtest_request.spec)
    expected = strategy_config(
        instrument_id=backtest_request.instrument_id,
        bar_type=backtest_request.bar_type,
        spec=spec.model_dump(mode="json", by_alias=True),
        strategy_version_id=backtest_request.strategy_version_id,
        spec_hash=spec_hash(spec),
        # Sizing must leave room for the commission it will pay, so the costs
        # travel with the strategy config.
        cost_bps=str(backtest_request.fees.taker_bps + backtest_request.slippage_bps),
    )
    assert build(backtest_request, builder_settings).engine.strategies[0] == expected


def test_the_strategy_paths_are_the_stored_ones(backtest_request: BacktestRequest, builder_settings: Settings) -> None:
    # These strings live inside stored configs; changing them is a migration.
    strategy = build(backtest_request, builder_settings).engine.strategies[0]
    assert strategy.strategy_path == STRATEGY_PATH == "engine.strategies.dsl_strategy:DslStrategy"
    assert strategy.config_path == CONFIG_PATH


def test_the_costs_travel_with_the_config(backtest_request: BacktestRequest, builder_settings: Settings) -> None:
    # Without this the strategy sizes a position it cannot pay the fee on, the
    # account overdraws, and the simulated exchange halts the whole run.
    config = build(backtest_request, builder_settings).engine.strategies[0].config
    assert config["cost_bps"] == "15"  # 10 bps taker + 5 bps slippage


def test_the_spec_hash_travels_with_the_config(backtest_request: BacktestRequest, builder_settings: Settings) -> None:
    spec = StrategySpec.model_validate(backtest_request.spec)
    config = build(backtest_request, builder_settings).engine.strategies[0].config
    assert config["spec_hash"] == spec_hash(spec)
    assert config["strategy_version_id"] == backtest_request.strategy_version_id


# --- data and venue ------------------------------------------------------


def test_the_data_window_matches_the_request(backtest_request: BacktestRequest, builder_settings: Settings) -> None:
    data = build(backtest_request, builder_settings).data[0]
    assert data.instrument_id == "BTCUSDT.BINANCE"
    assert data.bar_types == ["BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL"]
    assert "2023-01-01" in str(data.start_time)
    assert "2025-01-01" in str(data.end_time)


def test_the_catalog_path_comes_from_settings(backtest_request: BacktestRequest) -> None:
    settings = Settings(_env_file=None, catalog_path="/srv/other-catalog")
    assert build(backtest_request, settings).data[0].catalog_path == "/srv/other-catalog"


def test_the_venue_is_a_cash_account(backtest_request: BacktestRequest, builder_settings: Settings) -> None:
    venue = build(backtest_request, builder_settings).venues[0]
    assert venue.name == "BINANCE"
    assert str(venue.account_type) == "CASH"
    assert venue.starting_balances == ["10000 USDT"]


def test_reports_can_be_read_after_the_run(backtest_request: BacktestRequest, builder_settings: Settings) -> None:
    # dispose_on_completion defaults to True and clears the cache before run()
    # returns, which makes every report come back empty (D9).
    assert build(backtest_request, builder_settings).dispose_on_completion is False


def test_different_requests_produce_different_configs(request_dict: dict[str, Any], builder_settings: Settings) -> None:
    baseline = summarise(build(BacktestRequest.model_validate(request_dict), builder_settings))
    request_dict["slippageBps"] = "25"
    changed = summarise(build(BacktestRequest.model_validate(request_dict), builder_settings))
    assert changed != baseline


# --- the config actually runs -------------------------------------------


def test_the_built_config_runs_and_charges_costs(builder_settings: Settings) -> None:
    """End to end: what the builder produces is what Nautilus accepts.

    A config that assembles cleanly but is rejected by the engine would pass
    every other test in this file.
    """
    from pathlib import Path

    from nautilus_trader.backtest.node import BacktestNode

    if not Path("catalog/data/bar/BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL").exists():
        pytest.skip("needs the Phase 0 catalog")

    def total_commission(request: BacktestRequest) -> Decimal:
        node = BacktestNode(configs=[build(request, builder_settings)])
        node.run()
        engine = node.get_engines()[0]
        try:
            fills = engine.trader.generate_order_fills_report()
            total = Decimal(0)
            for cell in fills["commissions"]:
                for item in cell if isinstance(cell, list) else [cell]:
                    text = str(item)
                    if text and text != "nan":
                        total += Decimal(text.split()[0])
            return total
        finally:
            engine.dispose()

    window = {"start": "2024-01-01T00:00:00Z", "end": "2024-02-01T00:00:00Z"}
    charged = total_commission(BacktestRequest.model_validate({**REQUEST_FOR_RUN, **window}))
    free = total_commission(
        BacktestRequest.model_validate(
            {
                **REQUEST_FOR_RUN,
                **window,
                "fees": {"makerBps": "0", "takerBps": "0"},
                "slippageBps": "0",
            }
        )
    )

    assert free == 0
    assert charged > 0, "the fee model was configured but nothing was charged"
