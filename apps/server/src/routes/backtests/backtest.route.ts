import { createRoute, z } from '@hono/zod-openapi';
import * as HttpStatusCodes from 'stoker/http-status-codes';
import jsonContent from 'stoker/openapi/helpers/json-content';
import jsonContentRequired from 'stoker/openapi/helpers/json-content-required';

import { ApiErrorSchema } from '@quant/contracts/error';
import {
  BacktestListQuerySchema,
  BacktestListSchema,
  BacktestRunSchema,
  CreateBacktestSchema,
  EquitySeriesSchema,
  TradePageSchema,
  TradesQuerySchema,
} from '@quant/contracts/backtest';

const IdParam = z.object({ id: z.uuid() });
const unauthorized = jsonContent(ApiErrorSchema, 'Not authenticated');
const notFound = jsonContent(ApiErrorSchema, 'No such run');

export const listBacktestsRoute = createRoute({
  method: 'get',
  path: '/',
  tags: ['Backtests'],
  request: { query: BacktestListQuerySchema },
  responses: {
    [HttpStatusCodes.OK]: jsonContent(BacktestListSchema, "The user's runs, newest first"),
    [HttpStatusCodes.UNAUTHORIZED]: unauthorized,
  },
});

// Always a new run: the idempotency key is minted per row, so a retry of the
// same row can never become a second job.
export const createBacktestRoute = createRoute({
  method: 'post',
  path: '/',
  tags: ['Backtests'],
  request: { body: jsonContentRequired(CreateBacktestSchema, 'What to run, over which window, at what cost') },
  responses: {
    [HttpStatusCodes.CREATED]: jsonContent(BacktestRunSchema, 'The run, queued or still submitting'),
    [HttpStatusCodes.UNPROCESSABLE_ENTITY]: jsonContent(ApiErrorSchema, 'The spec or window is not runnable'),
    [HttpStatusCodes.NOT_FOUND]: jsonContent(ApiErrorSchema, 'No such strategy version'),
    [HttpStatusCodes.UNAUTHORIZED]: unauthorized,
  },
});

export const getBacktestRoute = createRoute({
  method: 'get',
  path: '/{id}',
  tags: ['Backtests'],
  request: { params: IdParam },
  responses: {
    [HttpStatusCodes.OK]: jsonContent(BacktestRunSchema, 'The run, refreshed from the engine if unfinished'),
    [HttpStatusCodes.NOT_FOUND]: notFound,
    [HttpStatusCodes.UNAUTHORIZED]: unauthorized,
  },
});

export const cancelBacktestRoute = createRoute({
  method: 'delete',
  path: '/{id}',
  tags: ['Backtests'],
  request: { params: IdParam },
  responses: {
    [HttpStatusCodes.OK]: jsonContent(BacktestRunSchema, 'The cancelled run'),
    [HttpStatusCodes.CONFLICT]: jsonContent(ApiErrorSchema, 'Already started or finished'),
    [HttpStatusCodes.NOT_FOUND]: notFound,
    [HttpStatusCodes.UNAUTHORIZED]: unauthorized,
  },
});

export const equityRoute = createRoute({
  method: 'get',
  path: '/{id}/equity',
  tags: ['Backtests'],
  request: { params: IdParam },
  responses: {
    [HttpStatusCodes.OK]: jsonContent(EquitySeriesSchema, 'Realized equity and drawdown, ~1,000 points'),
    [HttpStatusCodes.CONFLICT]: jsonContent(ApiErrorSchema, 'The run has not succeeded'),
    [HttpStatusCodes.NOT_FOUND]: notFound,
    [HttpStatusCodes.UNAUTHORIZED]: unauthorized,
  },
});

export const tradesRoute = createRoute({
  method: 'get',
  path: '/{id}/trades',
  tags: ['Backtests'],
  request: { params: IdParam, query: TradesQuerySchema },
  responses: {
    [HttpStatusCodes.OK]: jsonContent(TradePageSchema, 'One page of closed trades'),
    [HttpStatusCodes.CONFLICT]: jsonContent(ApiErrorSchema, 'The run has not succeeded'),
    [HttpStatusCodes.NOT_FOUND]: notFound,
    [HttpStatusCodes.UNAUTHORIZED]: unauthorized,
  },
});
