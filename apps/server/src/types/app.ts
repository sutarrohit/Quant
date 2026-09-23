import type { OpenAPIHono, RouteConfig, RouteHandler } from '@hono/zod-openapi';
import type { PinoLogger } from 'hono-pino';

import type { AuthUser } from './auth.js';

/** Extends Hono's context variables, so `c.get('user')` is typed in every handler. */
export interface AppBinding {
  Variables: {
    logger: PinoLogger;
    user: AuthUser;
  };
}

export type AppOpenAPI = OpenAPIHono<AppBinding>;
export type AppRouteHandler<R extends RouteConfig> = RouteHandler<R, AppBinding>;
