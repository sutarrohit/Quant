# engine

Python 3.13 uv project. Backtest, evaluator and Nautilus adapter code for the quant platform
(D-02).

## Layout

- `dsl/` — pure Python: `StrategySpec` and `DslEvaluator`. **Must never import
  `nautilus_trader`, or anything that transitively imports it, for any reason.** Success
  criterion 3 enforces this with a literal recursive grep over this directory
  (`grep -rl nautilus_trader engine/dsl/`), so even a comment naming that package inside `dsl/`
  would make the gate self-invalidating — that is why the rule lives here instead.
- `adapters/` — the sole file (`dsl_strategy.py`, added in a later plan) that imports both
  `DslEvaluator` and Nautilus.
- `data/` — Binance Vision ingestion and the daily `exchangeInfo` snapshot writer.
- `cli/` — the `backtest` entry point (D-17).
- `persistence/` — SQLAlchemy Core tables mirroring the Prisma-migrated schema (D-11).
- `tests/` — pytest suite, including `conftest.py`'s `synthetic_bars` fixture used by the DSL
  unit tests independent of any ingested data or the trading engine.

## Commands

```bash
uv sync --project engine        # install
uv run --project engine pytest  # test
uv run --project engine ruff check .  # lint
```
