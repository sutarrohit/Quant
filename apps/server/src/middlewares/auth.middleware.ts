import { getCookie } from 'hono/cookie';
import { createMiddleware } from 'hono/factory';

import { ApiError } from '../lib/api-error.js';
import { walletService } from '../lib/container.js';
import { prisma } from '../lib/prisma.js';
import { profileFromLinkedAccounts } from '../lib/privy-profile.js';
import { walletsFromLinkedAccounts, type PrivyWallet } from '../lib/privy-wallets.js';
import { privy } from '../lib/privy.js';
import type { AppBinding } from '../types/app.js';

// Verify a Privy token and attach the local user row, so handlers read
// `c.get('user')`. Cookie is the production path, header the fallback for when
// Privy is still on localStorage storage. See docs/privy-auth-integration.md 2.1-2.3.
export const requireAuth = createMiddleware<AppBinding>(async (c, next) => {
  const cookieToken = getCookie(c, 'privy-token');

  // Capture, not strip: /^Bearer\s+/ on a bare "Bearer" leaves that literal,
  // which reaches Privy as "invalid token" rather than "no credentials".
  const headerToken = c.req.header('authorization')?.match(/^Bearer\s+(\S.*)$/i)?.[1]?.trim();

  const token = cookieToken || headerToken; // `||` not `??`: empty should fall through.
  if (!token) throw new ApiError(401, 'UNAUTHORIZED', 'Authentication required');

  let claims;
  try {
    // Bare string in, snake_case out. Privy's docs show an object and `claims.userId`;
    // both are wrong against its published types, and `userId` would be undefined.
    claims = await privy.utils().auth().verifyAccessToken(token);
  } catch {
    throw new ApiError(401, 'UNAUTHORIZED', 'Invalid or expired token'); // Expired or forged.
  }

  // Just-in-time provisioning: a user's first authenticated request creates their row.
  // Read-then-create, not upsert -- the profile fetch below should happen once per
  // user, and wallet-only users legitimately never have an email to key off.
  let user = await prisma.user.findUnique({ where: { privyDid: claims.user_id } });

  if (!user) {
    let profile: { email: string | null; name: string | null } = { email: null, name: null };
    let wallets: PrivyWallet[] = [];
    try {
      const privyUser = await privy.users()._get(claims.user_id);
      profile = profileFromLinkedAccounts(privyUser.linked_accounts);
      // Same payload, no second call. Often empty -- the embedded wallet is created
      // in the browser, and POST /user/wallets/sync closes that gap.
      wallets = walletsFromLinkedAccounts(privyUser.linked_accounts);
    } catch (err) {
      // Non-fatal: the token already verified, so the request IS authenticated.
      c.get('logger')?.warn({ err }, 'privy profile lookup failed; provisioning DID-only');
    }

    try {
      user = await prisma.user.create({ data: { privyDid: claims.user_id, ...profile } });
    } catch {
      // Concurrent first requests both create; the loser re-reads rather than 500s.
      user = await prisma.user.findUnique({ where: { privyDid: claims.user_id } });
    }

    if (user && wallets.length > 0) {
      try {
        await walletService.sync(user.id, wallets);
      } catch (err) {
        // Also non-fatal: this sync is repeatable, so a failed write costs a retry.
        c.get('logger')?.warn({ err }, 'wallet sync failed during provisioning');
      }
    }
  }

  if (!user) throw new ApiError(401, 'UNAUTHORIZED', 'Could not resolve user');

  c.set('user', user);
  await next();
});
