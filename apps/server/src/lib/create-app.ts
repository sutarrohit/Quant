import { OpenAPIHono } from '@hono/zod-openapi';
import { notFound, onError, pinoLogger, rateLimiter } from '../middlewares/index.middleware.js';
import { AppBinding } from '../types/index.js';
import { defaultHook } from 'stoker/openapi';
import { cors } from 'hono/cors';
import env from '../env.js';

export function createRouter() {
  return new OpenAPIHono<AppBinding>({ strict: false, defaultHook });
}

export default function createApp() {
  const app = createRouter();
  app.use(pinoLogger());
  app.use(rateLimiter);

  // `credentials: true` is what lets the browser attach the privy-token cookie
  // on a cross-origin call. It requires an exact `origin` -- the browser rejects
  // a wildcard on any credentialed request, so FRONTEND_URL must never become '*'.
  // For multiple frontends, pass a function that echoes a match from an allowlist.
  app.use(
    '*',
    cors({
      origin: env.FRONTEND_URL,
      allowHeaders: ['Content-Type', 'Authorization'],
      allowMethods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
      credentials: true,
    })
  );

  app.notFound(notFound);
  app.onError(onError);

  return app;
}
