import { rateLimiter } from 'hono-rate-limiter';
import { getCookie } from 'hono/cookie';

import type { AppBinding } from '../types/app.js';

const limiter = rateLimiter<AppBinding>({
  windowMs: 10 * 60 * 1000, // 10-minute window
  limit: 1000, // Max 1000 requests per window
  standardHeaders: 'draft-7', // Use the standard RateLimit header

  // One bucket per signed-in user, falling back to the client IP.
  //
  // `c.get('user')` is the real key and is set by requireAuth -- but this
  // middleware is registered app-wide in create-app.ts, so it also runs for
  // public routes and for the unauthenticated half of a request. Hence the
  // cookie fallback: Privy's `privy-token` identifies the session before
  // requireAuth has verified it, which is enough to separate two users.
  //
  // It used to look for a cookie whose name contained `session_token`, which
  // Privy never sets -- so every signed-in user shared the per-IP bucket, and
  // two people behind one NAT polling two backtests would have spent half the
  // window between them.
  keyGenerator: (c) => {
    const userId = c.get('user')?.id;
    if (userId) return `user:${userId}`;

    const sessionToken = getCookie(c, 'privy-token');
    if (sessionToken) return `session:${sessionToken}`;

    const ip = c.req.header('x-forwarded-for')?.split(',')[0]?.trim() || c.req.header('x-real-ip');

    return ip ? `ip:${ip}` : 'anonymous';
  },
});

export default limiter;
