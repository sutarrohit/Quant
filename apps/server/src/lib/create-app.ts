import { OpenAPIHono } from '@hono/zod-openapi';
import { notFound, onError, pinoLogger, rateLimiter } from '../middlewares/index.middleware.js';
import type { AppBinding } from '../types/app.js';
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

  // `credentials: true` carries the privy-token cookie cross-origin, and needs an
  // exact `origin` -- FRONTEND_URL must never become '*'.
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
