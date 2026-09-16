import type { OpenAPIHono, RouteConfig, RouteHandler } from '@hono/zod-openapi';
import type { PinoLogger } from 'hono-pino';

// ---------------------------------------------------------------------------
// DEMO: This file defines shared types used across the app.
// AppBinding extends Hono's context variables so that `c.get('user')` and
// `c.get('logger')` are fully typed in route handlers.
// ---------------------------------------------------------------------------

// Local user row attached by requireAuth. Mirrors the Prisma `User` model.
//
// `name` and `email` are nullable because Privy identifies a user by DID, and a
// wallet-only login carries neither. Never key domain data off `email`.
export interface AuthUser {
  id: string;
  privyDid: string;
  name: string | null;
  email: string | null;
  image: string | null;
  onboardingCompletedAt: Date | null;
  createdAt: Date;
  updatedAt: Date;
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
