import * as HttpStatusCodes from 'stoker/http-status-codes';

import { ApiError } from '../../lib/api-error.js';
import { userService, walletService } from '../../lib/container.js';
import type { AppRouteHandler } from '../../types/index.js';
import type {
  completeOnboardingRoute,
  getOnboardingStatusRoute,
  listWalletsRoute,
  syncWalletsRoute,
} from './user.route.js';

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

// The row carries `id`/`userId` and Date objects; the wire carries neither.
// `toISOString()` rather than letting JSON.stringify do it implicitly, so the
// nullable case is handled where it can be seen.
const toWireWallet = (wallet: {
  address: string;
  chainType: string;
  walletClient: string;
  firstVerifiedAt: Date | null;
}) => ({
  address: wallet.address,
  chainType: wallet.chainType,
  walletClient: wallet.walletClient,
  firstVerifiedAt: wallet.firstVerifiedAt?.toISOString() ?? null,
});

// Handler for GET /wallets
export const listWalletsHandler: AppRouteHandler<typeof listWalletsRoute> = async (c) => {
  const user = c.get('user');

  const wallets = await walletService.list(user.id);
  return c.json({ wallets: wallets.map(toWireWallet) }, HttpStatusCodes.OK);
};

// Handler for POST /wallets/sync
export const syncWalletsHandler: AppRouteHandler<typeof syncWalletsRoute> = async (c) => {
  const user = c.get('user');

  let result;
  try {
    result = await walletService.syncFromPrivy(user.id, user.privyDid);
  } catch (err) {
    // Privy is a third party on the far side of the network. A failure here is
    // theirs or the link's, not the caller's -- 502 says so, and says the same
    // request is worth retrying, which a 500 does not.
    c.get('logger')?.error({ err }, 'privy wallet sync failed');
    throw new ApiError(HttpStatusCodes.BAD_GATEWAY, 'PRIVY_UNAVAILABLE', 'Could not reach Privy to sync wallets');
  }

  // A wallet Privy reports for this user but that is already recorded against
  // another one. Not an error for the caller -- their own wallets are returned
  // either way -- but it is worth knowing about, because for an embedded wallet
  // it should be impossible.
  if (result.conflicts.length > 0) {
    c.get('logger')?.warn({ conflicts: result.conflicts, userId: user.id }, 'wallet already linked to another user');
  }

  return c.json({ wallets: result.wallets.map(toWireWallet) }, HttpStatusCodes.OK);
};
