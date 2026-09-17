import { getCookie } from 'hono/cookie';
import { createMiddleware } from 'hono/factory';

import { ApiError } from '../lib/api-error.js';
import { walletService } from '../lib/container.js';
import { prisma } from '../lib/prisma.js';
import { profileFromLinkedAccounts } from '../lib/privy-profile.js';
import { walletsFromLinkedAccounts, type PrivyWallet } from '../lib/privy-wallets.js';
import { privy } from '../lib/privy.js';
import type { AppBinding } from '../types/index.js';

// Require a valid Privy access token; attach the local user row to the context
// so handlers can read `c.get('user')`.
//
// The token is read from the `privy-token` cookie first, falling back to an
// `Authorization: Bearer` header. Both are accepted on purpose:
//
//   - Cookie is the production path. Privy's servers set it via Set-Cookie, so
//     it is genuinely HttpOnly and unreadable by page scripts. Note the dev app
//     ID sets the cookie from JavaScript, which cannot apply that flag -- so do
//     not read "works locally" as having proven the XSS property.
//   - Header is the fallback. It works when Privy is still on its default
//     localStorage storage, which keeps cookie setup off the critical path for
//     local development.
//
// Accepting both costs nothing: a cross-origin attacker cannot set a custom
// header without our CORS approval, so the header path adds no CSRF surface
// beyond what the cookie already has. See docs/privy-auth-integration.md 2.1-2.3.
export const requireAuth = createMiddleware<AppBinding>(async (c, next) => {
  const cookieToken = getCookie(c, 'privy-token');

  // Capture rather than strip. A bare `Authorization: Bearer` with no token must
  // not match -- stripping with /^Bearer\s+/ leaves the literal string "Bearer",
  // which then reaches Privy and returns a misleading "invalid token" instead of
  // "no credentials".
  const headerToken = c.req.header('authorization')?.match(/^Bearer\s+(\S.*)$/i)?.[1]?.trim();

  // `||` not `??`: an empty string from either source should fall through to the
  // other rather than short-circuit.
  const token = cookieToken || headerToken;
  if (!token) throw new ApiError(401, 'UNAUTHORIZED', 'Authentication required');

  let claims;
  try {
    // NOTE: takes a bare string, and returns snake_case fields. Privy's own docs
    // show `verifyAccessToken({ access_token })` returning `claims.userId`;
    // both are wrong against @privy-io/node's published types, and `claims.userId`
    // would silently be `undefined` here. Verified against VerifyAccessTokenResponse.
    claims = await privy.utils().auth().verifyAccessToken(token);
  } catch {
    // Expired or forged. A live session refreshes and retries; the client
    // distinguishes those cases, not us.
    throw new ApiError(401, 'UNAUTHORIZED', 'Invalid or expired token');
  }

  // Just-in-time provisioning: Privy is the identity source of truth, so the
  // first authenticated request a user ever makes is what creates their local row.
  //
  // Deliberately a read-then-create rather than an upsert. The token carries only
  // the DID, so email and name need a separate API call to Privy, and that call
  // should happen once in a user's lifetime -- not on every request. Keying the
  // fetch off "row is missing an email" would re-fetch forever for wallet-only
  // users, who legitimately never have one.
  let user = await prisma.user.findUnique({ where: { privyDid: claims.user_id } });

  if (!user) {
    let profile: { email: string | null; name: string | null } = { email: null, name: null };
    let wallets: PrivyWallet[] = [];
    try {
      const privyUser = await privy.users()._get(claims.user_id);
      profile = profileFromLinkedAccounts(privyUser.linked_accounts);
      // Same payload, no second call. Often empty at this point: the embedded
      // wallet is created in the browser, so the first authenticated request can
      // beat it. POST /user/wallets/sync is what closes that gap.
      wallets = walletsFromLinkedAccounts(privyUser.linked_accounts);
    } catch (err) {
      // Non-fatal. The token already verified, so the request IS authenticated;
      // failing it because Privy's REST API blipped would be worse than a row
      // with null profile fields.
      c.get('logger')?.warn({ err }, 'privy profile lookup failed; provisioning DID-only');
    }

    try {
      user = await prisma.user.create({ data: { privyDid: claims.user_id, ...profile } });
    } catch {
      // Concurrent first requests race here: both see no row, both create, one
      // loses on the unique index. Re-read rather than surface a 500.
      user = await prisma.user.findUnique({ where: { privyDid: claims.user_id } });
    }

    if (user && wallets.length > 0) {
      try {
        await walletService.sync(user.id, wallets);
      } catch (err) {
        // Also non-fatal, and for the same reason: the wallet is Privy's to own
        // and this sync is repeatable, so a failed write costs one round trip on
        // the next sync rather than the user's session.
        c.get('logger')?.warn({ err }, 'wallet sync failed during provisioning');
      }
    }
  }

  if (!user) throw new ApiError(401, 'UNAUTHORIZED', 'Could not resolve user');

  c.set('user', user);
  await next();
});
