import { getCookie } from 'hono/cookie';
import { createMiddleware } from 'hono/factory';

import { ApiError } from '../lib/api-error.js';
import { prisma } from '../lib/prisma.js';
import { privy } from '../lib/privy.js';
import type { AppBinding } from '../types/index.js';

// Require a valid Privy access token; attach the local user row to the context
// so handlers can read `c.get('user')`.
//
// The token arrives in the `privy-token` cookie rather than an Authorization
// header. That cookie is HttpOnly -- and so unreadable by page scripts -- only
// in production, where Privy's servers set it via Set-Cookie. The development
// app ID sets it from JavaScript, which cannot apply the flag, so do not read
// "works locally" as having proven the XSS property.
//
// Cookies are scoped by host and ignore ports, which is why :3000 -> :4000 works
// in dev with no extra setup. See docs/privy-auth-integration.md sections 2.1
// and 2.2.
export const requireAuth = createMiddleware<AppBinding>(async (c, next) => {
  const token = getCookie(c, 'privy-token');
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
  // first authenticated request a user ever makes is what creates their local
  // row. `update: {}` makes this a no-op read on every subsequent request.
  const user = await prisma.user.upsert({
    where: { privyDid: claims.user_id },
    create: { privyDid: claims.user_id },
    update: {},
  });

  c.set('user', user);
  await next();
});
