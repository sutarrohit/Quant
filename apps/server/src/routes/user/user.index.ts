import { createRouter } from '../../lib/create-app.js';

import { completeOnboardingHandler, getOnboardingStatusHandler } from './user.handler.js';
import { completeOnboardingRoute, getOnboardingStatusRoute } from './user.route.js';

// ---------------------------------------------------------------------------
// DEMO: This is the user router. It registers all user-related OpenAPI routes
// and their corresponding handlers. The router is mounted in app.ts at
// /api/v1/user, so all routes here are prefixed with that path.
//
// Example endpoints:
//   GET  /api/v1/user/onboarding-status   → { completed: boolean }
//   POST /api/v1/user/complete-onboarding → 204 No Content
// ---------------------------------------------------------------------------

const userRouter = createRouter()
  .openapi(getOnboardingStatusRoute, getOnboardingStatusHandler)
  .openapi(completeOnboardingRoute, completeOnboardingHandler);

export default userRouter;
