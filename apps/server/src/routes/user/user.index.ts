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

// ---------------------------------------------------------------------------
// DEMO: This is the user router. It registers all user-related OpenAPI routes
// and their corresponding handlers. The router is mounted in app.ts at
// /api/v1/user, so all routes here are prefixed with that path.
//
// Example endpoints:
//   GET  /api/v1/user/onboarding-status   → { completed: boolean }
//   POST /api/v1/user/complete-onboarding → 204 No Content
//   GET  /api/v1/user/wallets             → { wallets: [...] }
//   POST /api/v1/user/wallets/sync        → { wallets: [...] } (re-read from Privy)
// ---------------------------------------------------------------------------

const userRouter = createRouter();

// requireAuth runs before every route on this router, so `c.get('user')` is
// always populated in the handlers below. Without this line the routes are
// publicly readable -- which is exactly what the better-auth scaffold got wrong.
//
// Applied as its own statement rather than chained: Hono's `use()` is typed to
// return `Hono<...>`, not `this`, so chaining it ahead of `.openapi()` would
// erase the OpenAPIHono type that `.openapi()` lives on.
userRouter.use('*', requireAuth);

export default userRouter
  .openapi(getOnboardingStatusRoute, getOnboardingStatusHandler)
  .openapi(completeOnboardingRoute, completeOnboardingHandler)
  .openapi(listWalletsRoute, listWalletsHandler)
  .openapi(syncWalletsRoute, syncWalletsHandler);
