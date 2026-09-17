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

// The wallet as the API hands it out. Deliberately not the row: `id` and `userId`
// are internal, and `walletClient` is the field a client actually needs -- 'privy'
// is the embedded wallet created at login, anything else the user connected.
export const WalletSchema = z.object({
  address: z.string(),
  chainType: z.string(),
  walletClient: z.string(),
  firstVerifiedAt: z.string().datetime().nullable(),
});

export const WalletListSchema = z.object({ wallets: z.array(WalletSchema) });

// GET route -- the wallets already stored for the authenticated user. This is what
// the platform will key off, so reading it back is how a client tells "Privy made a
// wallet" from "we have recorded it".
export const listWalletsRoute = createRoute({
  method: 'get',
  path: '/wallets',
  tags: ['User'],
  responses: {
    [HttpStatusCodes.OK]: jsonContent(WalletListSchema, "The user's stored wallets"),
    [HttpStatusCodes.UNAUTHORIZED]: jsonContent(ApiErrorSchema, 'Not authenticated'),
  },
});

// POST route -- re-read the user's wallets from Privy and store what it reports.
//
// It takes no body on purpose. The embedded wallet is created in the browser, so
// the client is what knows *when* a wallet appeared; it is never what says which
// address it is. The server asks Privy and believes only that.
//
// Idempotent, and safe to call whenever the client sees a wallet the server has
// not returned yet.
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
