"""Simulated execution against a live feed — Nautilus's `sandbox` environment.

The third of the three ways a strategy runs here, and the one that is easy to
get subtly wrong because it looks like both of the others:

| Environment | Data | Execution | Money |
|---|---|---|---|
| `backtest` (`engine.backtest`) | historical, from the catalog | simulated | none |
| `sandbox` (this package) | **live**, from the venue | simulated | none |
| `live` (`engine.live`) | live | **real** | real |

Same `DslStrategy`, same config factory, same order path in all three. What
changes is where the bars come from and who fills the order.
"""
