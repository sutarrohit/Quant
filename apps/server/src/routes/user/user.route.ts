import { createRoute, z } from '@hono/zod-openapi';
import * as HttpStatusCodes from 'stoker/http-status-codes';
import jsonContent from 'stoker/openapi/helpers/json-content';
import { ApiErrorSchema } from '../../types/error.js';

// Schema for the onboarding status response.
export const OnboardingStatusSchema = z.object({ completed: z.boolean() });

// DEMO: GET route — returns whether the authenticated user has completed
// onboarding. The web dashboard reads this to decide the first-login redirect.
export const getOnboardingStatusRoute = createRoute({
  method: 'get',
  path: '/onboarding-status',
  tags: ['User'],
  responses: {
    [HttpStatusCodes.OK]: jsonContent(OnboardingStatusSchema, 'Whether the user finished onboarding'),
    [HttpStatusCodes.UNAUTHORIZED]: jsonContent(ApiErrorSchema, 'Not authenticated'),
  },
});

// DEMO: POST route — marks onboarding as complete for the current user.
// This operation is idempotent: calling it multiple times won't change the
// timestamp after the first completion.
export const completeOnboardingRoute = createRoute({
  method: 'post',
  path: '/complete-onboarding',
  tags: ['User'],
  responses: {
    [HttpStatusCodes.NO_CONTENT]: { description: 'Onboarding marked complete' },
    [HttpStatusCodes.UNAUTHORIZED]: jsonContent(ApiErrorSchema, 'Not authenticated'),
  },
});
