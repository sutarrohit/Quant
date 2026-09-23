import { createRouter } from '../../lib/create-app.js';
import { requireAuth } from '../../middlewares/index.middleware.js';

import {
  cancelBacktestHandler,
  createBacktestHandler,
  equityHandler,
  getBacktestHandler,
  listBacktestsHandler,
  tradesHandler,
} from './backtest.handler.js';
import {
  cancelBacktestRoute,
  createBacktestRoute,
  equityRoute,
  getBacktestRoute,
  listBacktestsRoute,
  tradesRoute,
} from './backtest.route.js';

// Mounted at /api/v1/backtests.
const backtestRouter = createRouter();

backtestRouter.use('*', requireAuth);

export default backtestRouter
  .openapi(listBacktestsRoute, listBacktestsHandler)
  .openapi(createBacktestRoute, createBacktestHandler)
  .openapi(getBacktestRoute, getBacktestHandler)
  .openapi(cancelBacktestRoute, cancelBacktestHandler)
  .openapi(equityRoute, equityHandler)
  .openapi(tradesRoute, tradesHandler);
