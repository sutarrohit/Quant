import { createMiddleware } from 'hono/factory';

import { ApiError } from '../lib/api-error.js';
import { auth } from '../lib/auth.js';
import type { AppBinding } from '../types/index.js';

// Require a valid better-auth session; attach the user to the context so
// handlers can read `c.get("user")`.
export const requireAuth = createMiddleware<AppBinding>(async (c, next) => {
  const session = await auth.api.getSession({ headers: c.req.raw.headers });
  if (!session) throw new ApiError(401, 'UNAUTHORIZED', 'Authentication required');

  c.set('user', session.user);
  await next();
});
