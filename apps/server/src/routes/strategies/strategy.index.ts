import { createRouter } from '../../lib/create-app.js';
import { requireAuth } from '../../middlewares/index.middleware.js';

import {
  archiveStrategyHandler,
  createStrategyHandler,
  createVersionHandler,
  getStrategyHandler,
  listStrategiesHandler,
  validateSpecHandler,
} from './strategy.handler.js';
import {
  archiveStrategyRoute,
  createStrategyRoute,
  createVersionRoute,
  getStrategyRoute,
  listStrategiesRoute,
  validateSpecRoute,
} from './strategy.route.js';

// Mounted at /api/v1/strategies.
const strategyRouter = createRouter();

strategyRouter.use('*', requireAuth);

// `validate` is registered before `/{id}`, or Hono matches it as an id.
export default strategyRouter
  .openapi(validateSpecRoute, validateSpecHandler)
  .openapi(listStrategiesRoute, listStrategiesHandler)
  .openapi(createStrategyRoute, createStrategyHandler)
  .openapi(getStrategyRoute, getStrategyHandler)
  .openapi(createVersionRoute, createVersionHandler)
  .openapi(archiveStrategyRoute, archiveStrategyHandler);
