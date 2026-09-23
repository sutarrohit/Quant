import { TIMEFRAME_AGGREGATION } from '@quant/contracts/backtest';
import type { StrategySpec } from '@quant/contracts/spec';

import { ApiError } from './api-error.js';

/** Nautilus spells a pair "SOLUSDT.BINANCE"; the spec spells it "SOL/USDT". */
export const instrumentIdOf = (spec: StrategySpec, symbol: string) =>
  `${symbol.replace('/', '').toUpperCase()}.${spec.market.exchange.toUpperCase()}`;

/**
 * The market fields must name something the spec trades, or the run tests a
 * different strategy than the one saved.
 */
export function assertMatchesSpec(spec: StrategySpec, input: { instrumentId: string; barType: string }): void {
  const instruments = spec.market.symbols.map((symbol) => instrumentIdOf(spec, symbol));
  const barType = `${input.instrumentId}-${TIMEFRAME_AGGREGATION[spec.market.timeframe]}-LAST-EXTERNAL`;

  const problem = !instruments.includes(input.instrumentId)
    ? { path: 'instrumentId', message: `must be one of ${instruments.join(', ')}` }
    : input.barType !== barType
      ? { path: 'barType', message: `must be ${barType} for a ${spec.market.timeframe} strategy` }
      : null;

  if (problem) throw new ApiError(422, 'REQUEST_INVALID', problem.message, [problem]);
}
