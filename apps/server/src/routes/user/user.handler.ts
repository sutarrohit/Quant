import * as HttpStatusCodes from 'stoker/http-status-codes';

import { ApiError } from '../../lib/api-error.js';
import { userService, walletService } from '../../lib/container.js';
import type { AppRouteHandler } from '../../types/app.js';
import type {
  completeOnboardingRoute,
  getOnboardingStatusRoute,
  listWalletsRoute,
  syncWalletsRoute,
} from './user.route.js';

// `c.get('user')` is set by requireAuth earlier in the request.
export const getOnboardingStatusHandler: AppRouteHandler<typeof getOnboardingStatusRoute> = async (c) => {
  const user = c.get('user');

  const status = await userService.getOnboardingStatus(user.id);
  return c.json(status, HttpStatusCodes.OK);
};

export const completeOnboardingHandler: AppRouteHandler<typeof completeOnboardingRoute> = async (c) => {
  const user = c.get('user');
  await userService.completeOnboarding(user.id);
  return c.body(null, HttpStatusCodes.NO_CONTENT);
};

// The row carries `id`/`userId` and Dates; the wire carries neither. Explicit
// `toISOString()` so the nullable case is handled where it can be seen.
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

export const listWalletsHandler: AppRouteHandler<typeof listWalletsRoute> = async (c) => {
  const user = c.get('user');

  const wallets = await walletService.list(user.id);
  return c.json({ wallets: wallets.map(toWireWallet) }, HttpStatusCodes.OK);
};

export const syncWalletsHandler: AppRouteHandler<typeof syncWalletsRoute> = async (c) => {
  const user = c.get('user');

  let result;
  try {
    result = await walletService.syncFromPrivy(user.id, user.privyDid);
  } catch (err) {
    // 502, not 500: the failure is Privy's or the link's, and retrying is worth it.
    c.get('logger')?.error({ err }, 'privy wallet sync failed');
    throw new ApiError(HttpStatusCodes.BAD_GATEWAY, 'PRIVY_UNAVAILABLE', 'Could not reach Privy to sync wallets');
  }

  // Not an error for the caller, but worth knowing: for an embedded wallet it
  // should be impossible.
  if (result.conflicts.length > 0) {
    c.get('logger')?.warn({ conflicts: result.conflicts, userId: user.id }, 'wallet already linked to another user');
  }

  return c.json({ wallets: result.wallets.map(toWireWallet) }, HttpStatusCodes.OK);
};
