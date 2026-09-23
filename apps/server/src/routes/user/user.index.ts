import { createRouter } from '../../lib/create-app.js';
import { requireAuth } from '../../middlewares/index.middleware.js';

import {
  completeOnboardingHandler,
  getOnboardingStatusHandler,
  listWalletsHandler,
  syncWalletsHandler,
} from './user.handler.js';
import {
  completeOnboardingRoute,
  getOnboardingStatusRoute,
  listWalletsRoute,
  syncWalletsRoute,
} from './user.route.js';

// Mounted at /api/v1/user.
const userRouter = createRouter();

// Its own statement, not chained: Hono's `use()` returns `Hono<...>` rather than
// `this`, so chaining would erase the OpenAPIHono type `.openapi()` lives on.
userRouter.use('*', requireAuth);

export default userRouter
  .openapi(getOnboardingStatusRoute, getOnboardingStatusHandler)
  .openapi(completeOnboardingRoute, completeOnboardingHandler)
  .openapi(listWalletsRoute, listWalletsHandler)
  .openapi(syncWalletsRoute, syncWalletsHandler);
