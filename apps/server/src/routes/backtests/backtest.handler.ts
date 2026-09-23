import * as HttpStatusCodes from 'stoker/http-status-codes';

import { backtestService } from '../../lib/container.js';
import type { RunWithVersion } from '../../services/backtest.service.js';
import type { AppRouteHandler } from '../../types/app.js';
import type { BacktestRun, BacktestSummary, RunStatus } from '@quant/contracts/backtest';
import type {
  cancelBacktestRoute,
  createBacktestRoute,
  equityRoute,
  getBacktestRoute,
  listBacktestsRoute,
  tradesRoute,
} from './backtest.route.js';

const toWireRun = (run: RunWithVersion): BacktestRun => ({
  id: run.id,
  status: run.status as RunStatus,
  strategyId: run.version.strategyId,
  strategyName: run.version.strategy.name,
  versionId: run.versionId,
  version: run.version.version,
  venue: run.venue,
  instrumentId: run.instrumentId,
  barType: run.barType,
  start: run.windowStart.toISOString(),
  end: run.windowEnd.toISOString(),
  startingBalances: run.startingBalances,
  fees: { makerBps: run.makerBps.toString(), takerBps: run.takerBps.toString() },
  slippageBps: run.slippageBps.toString(),
  summary: (run.summary as BacktestSummary | null) ?? null,
  error: run.errorCode ? { code: run.errorCode, message: run.errorMessage ?? '' } : null,
  submittedAt: run.submittedAt.toISOString(),
  startedAt: run.startedAt ?? null,
  finishedAt: run.finishedAt?.toISOString() ?? null,
});

export const listBacktestsHandler: AppRouteHandler<typeof listBacktestsRoute> = async (c) => {
  const { page, pageSize, strategyId } = c.req.valid('query');
  const result = await backtestService.list(c.get('user').id, page, pageSize, strategyId);
  return c.json({ ...result, data: result.data.map(toWireRun) }, HttpStatusCodes.OK);
};

export const createBacktestHandler: AppRouteHandler<typeof createBacktestRoute> = async (c) => {
  const run = await backtestService.create(c.get('user').id, c.req.valid('json'));
  return c.json(toWireRun(run), HttpStatusCodes.CREATED);
};

export const getBacktestHandler: AppRouteHandler<typeof getBacktestRoute> = async (c) => {
  const run = await backtestService.get(c.get('user').id, c.req.valid('param').id);
  return c.json(toWireRun(run), HttpStatusCodes.OK);
};

export const cancelBacktestHandler: AppRouteHandler<typeof cancelBacktestRoute> = async (c) => {
  const run = await backtestService.cancel(c.get('user').id, c.req.valid('param').id);
  return c.json(toWireRun(run), HttpStatusCodes.OK);
};

export const equityHandler: AppRouteHandler<typeof equityRoute> = async (c) => {
  const curve = await backtestService.equity(c.get('user').id, c.req.valid('param').id);
  return c.json(curve, HttpStatusCodes.OK);
};

export const tradesHandler: AppRouteHandler<typeof tradesRoute> = async (c) => {
  const { offset, limit } = c.req.valid('query');
  const page = await backtestService.trades(c.get('user').id, c.req.valid('param').id, offset, limit);
  return c.json(page, HttpStatusCodes.OK);
};
