import { createRoute } from '@hono/zod-openapi';
import * as HttpStatusCodes from 'stoker/http-status-codes';
import jsonContent from 'stoker/openapi/helpers/json-content';
import { ApiErrorSchema } from '@quant/contracts/error';
import { OnboardingStatusSchema, WalletListSchema } from '../../types/user.js';

// The web dashboard reads this to decide the first-login redirect.
export const getOnboardingStatusRoute = createRoute({
  method: 'get',
  path: '/onboarding-status',
  tags: ['User'],
  responses: {
    [HttpStatusCodes.OK]: jsonContent(OnboardingStatusSchema, 'Whether the user finished onboarding'),
    [HttpStatusCodes.UNAUTHORIZED]: jsonContent(ApiErrorSchema, 'Not authenticated'),
  },
});

// Idempotent: repeat calls do not move the timestamp.
export const completeOnboardingRoute = createRoute({
  method: 'post',
  path: '/complete-onboarding',
  tags: ['User'],
  responses: {
    [HttpStatusCodes.NO_CONTENT]: { description: 'Onboarding marked complete' },
    [HttpStatusCodes.UNAUTHORIZED]: jsonContent(ApiErrorSchema, 'Not authenticated'),
  },
});

// Reading this back is how a client tells "Privy made a wallet" from "we stored it".
export const listWalletsRoute = createRoute({
  method: 'get',
  path: '/wallets',
  tags: ['User'],
  responses: {
    [HttpStatusCodes.OK]: jsonContent(WalletListSchema, "The user's stored wallets"),
    [HttpStatusCodes.UNAUTHORIZED]: jsonContent(ApiErrorSchema, 'Not authenticated'),
  },
});

// No body on purpose: the client knows *when* a wallet appeared, never which
// address it is. Idempotent, so call it whenever a wallet is missing.
export const syncWalletsRoute = createRoute({
  method: 'post',
  path: '/wallets/sync',
  tags: ['User'],
  responses: {
    [HttpStatusCodes.OK]: jsonContent(WalletListSchema, 'The wallets stored after syncing with Privy'),
    [HttpStatusCodes.UNAUTHORIZED]: jsonContent(ApiErrorSchema, 'Not authenticated'),
    [HttpStatusCodes.BAD_GATEWAY]: jsonContent(ApiErrorSchema, 'Privy could not be reached'),
  },
});
