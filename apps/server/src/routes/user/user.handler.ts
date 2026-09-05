import * as HttpStatusCodes from 'stoker/http-status-codes';

import { userService } from '../../lib/container.js';
import type { AppRouteHandler } from '../../types/index.js';
import type { completeOnboardingRoute, getOnboardingStatusRoute } from './user.route.js';

// ---------------------------------------------------------------------------
// DEMO: Route handlers receive the Hono context (`c`) and return a response.
// The authenticated user is available via `c.get('user')` — this is set by
// the auth middleware earlier in the request lifecycle.
// ---------------------------------------------------------------------------

// Handler for GET /onboarding-status
export const getOnboardingStatusHandler: AppRouteHandler<typeof getOnboardingStatusRoute> = async (c) => {
  const user = c.get('user');

  const status = await userService.getOnboardingStatus(user.id);
  return c.json(status, HttpStatusCodes.OK);
};

// Handler for POST /complete-onboarding
export const completeOnboardingHandler: AppRouteHandler<typeof completeOnboardingRoute> = async (c) => {
  const user = c.get('user');
  await userService.completeOnboarding(user.id);
  return c.body(null, HttpStatusCodes.NO_CONTENT);
};
