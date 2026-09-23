import type {
  BacktestList,
  BacktestListQuery,
  BacktestRun,
  CreateBacktestInput,
  EquitySeries,
  TradePage,
  TradesQuery,
} from '@quant/contracts/backtest';

import { request } from '@/utils/request';

// One function per route in apps/server/src/routes/backtests/.

const qs = (params: Record<string, unknown>) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined) search.set(key, String(value));
  const s = search.toString();
  return s ? `?${s}` : '';
};

// GET /api/v1/backtests -- newest first; unfinished runs are refreshed from the engine.
export async function getBacktests(query: BacktestListQuery = {}): Promise<BacktestList> {
  return request(`/backtests${qs(query)}`, { method: 'GET' });
}

// GET /api/v1/backtests/:id
export async function getBacktest(id: string): Promise<BacktestRun> {
  return request(`/backtests/${id}`, { method: 'GET' });
}

// POST /api/v1/backtests. A spec the window cannot run throws ApiError with `specErrors`.
export async function createBacktest(input: CreateBacktestInput): Promise<BacktestRun> {
  return request('/backtests', { method: 'POST', body: JSON.stringify(input) });
}

// DELETE /api/v1/backtests/:id -- cancel; 409 once the engine has started it.
export async function cancelBacktest(id: string): Promise<BacktestRun> {
  return request(`/backtests/${id}`, { method: 'DELETE' });
}

// GET /api/v1/backtests/:id/equity -- ~1,000 points, realized equity only.
export async function getEquity(id: string): Promise<EquitySeries> {
  return request(`/backtests/${id}/equity`, { method: 'GET' });
}

// GET /api/v1/backtests/:id/trades
export async function getTrades(id: string, query: TradesQuery = {}): Promise<TradePage> {
  return request(`/backtests/${id}/trades${qs(query)}`, { method: 'GET' });
}
