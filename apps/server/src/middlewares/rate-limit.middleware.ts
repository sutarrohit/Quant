import { rateLimiter } from 'hono-rate-limiter';
import { getCookie } from 'hono/cookie';
import { AppBinding } from '../types/index.js';

const limiter = rateLimiter<AppBinding>({
  windowMs: 10 * 60 * 1000, // 10-minute window
  limit: 1000, // Max 1000 requests per window
  standardHeaders: 'draft-7', // Use the standard RateLimit header

  // Use session cookie to rate limit each logged-in user independently.
  // Fall back to client IP, then a shared anonymous bucket.
  keyGenerator: (c) => {
    const cookies = getCookie(c);
    const sessionToken = Object.entries(cookies).find(([name]) => name.includes('session_token'))?.[1];

    if (sessionToken) return `user:${sessionToken}`;

    const ip = c.req.header('x-forwarded-for')?.split(',')[0]?.trim() || c.req.header('x-real-ip');

    return ip ? `ip:${ip}` : 'anonymous';
  },
});

export default limiter;
