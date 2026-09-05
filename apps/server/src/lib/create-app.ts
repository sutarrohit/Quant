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

  app.use(
    '*',
    cors({
      origin: env.FRONTEND_URL,
      allowMethods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
      credentials: true,
    })
  );

  app.notFound(notFound);
  app.onError(onError);

  return app;
}
