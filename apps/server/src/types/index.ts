import type { OpenAPIHono, RouteConfig, RouteHandler } from '@hono/zod-openapi';
import type { PinoLogger } from 'hono-pino';

// ---------------------------------------------------------------------------
// DEMO: This file defines shared types used across the app.
// AppBinding extends Hono's context variables so that `c.get('user')` and
// `c.get('logger')` are fully typed in route handlers.
// ---------------------------------------------------------------------------

// User shape set by the auth middleware on the Hono context.
//
// NOTE: there is currently NO auth middleware. better-auth was removed and Privy
// has not been wired up yet (see docs/privy-auth-integration.md), so `c.get('user')`
// is undefined at runtime and every route below is unauthenticated. This interface
// is a placeholder kept so the existing handlers still type-check; the Privy work
// replaces it with a `privyDid`-keyed shape.
export interface AuthUser {
  id: string;
  name: string;
  email: string;
  image?: string | null;
}

// Shared Hono/OpenAPI types used across the app and its routes.
export interface AppBinding {
  Variables: {
    logger: PinoLogger;
    user: AuthUser;
  };
}

export type AppOpenAPI = OpenAPIHono<AppBinding>;
export type AppRouteHandler<R extends RouteConfig> = RouteHandler<R, AppBinding>;

// Generic envelope for paginated list endpoints.
export type PaginatedResult<T> = {
  data: T[];
  pagination: {
    page: number;
    pageSize: number;
    total: number;
    totalPages: number;
  };
};
