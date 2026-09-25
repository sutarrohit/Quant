# AGENTS.md — apps/server (`@quant/api`)

Guidance for any coding agent working in `apps/server`. `CLAUDE.md` imports this file. The root `AGENTS.md` (working
agreement, monorepo layout) applies too.

## Commands

```bash
pnpm --filter @quant/api dev                                   # tsx watch on :4000, Swagger UI at /docs
pnpm --filter @quant/api test                                  # vitest run (tests/unit, tests/integration)
pnpm --filter @quant/api exec vitest run tests/unit/engine-client.test.ts
pnpm --filter @quant/api exec vitest run -t "camelize"
pnpm --filter @quant/api lint
pnpm --filter @quant/api check-types
```

Env: `src/env.ts` loads `.env`, `.env.test` or `.env.production` by `NODE_ENV` and exits on invalid values. It needs
`DATABASE_URL`, the Privy keys, and `ENGINE_INTERNAL_API_KEY` (must equal the engine's `NT_INTERNAL_API_KEY`). ESM with
`NodeNext` resolution, so relative imports end in `.js`.

## Structure

- **Routes:** `src/routes/<name>/` holds three files. `*.route.ts` has the `createRoute` definitions, built from
  `@quant/contracts` schemas plus `ApiErrorSchema` for every error status. `*.handler.ts` has `AppRouteHandler<typeof
  route>` functions. `*.index.ts` chains `.openapi(route, handler)` on `createRouter()` and applies `requireAuth`.
  Mount new routers in `src/app.ts`. Register literal paths (e.g. `/validate`) before `/{id}`.
- **Services:** `src/services/*.service.ts` classes take `PrismaClient` in the constructor and are instantiated once in
  `src/lib/container.ts`. Handlers import them from there. Tests construct services directly with fakes.
- **Errors:** throw `ApiError(status, CODE, message, details?)`. `middlewares/on-error.middleware.ts` shapes every
  error as `{ statusCode, code, message, details?, requestId }`. Codes are a contract with the web app.
- **Auth:** `requireAuth` verifies the Privy token (cookie first, then bearer header), provisions the `User` row on the
  first request, and sets `c.get('user')`. Every service read and write filters by that user's id. The engine has
  no concept of users, so ownership is enforced here or nowhere.
- **Engine:** `src/lib/engine-client.ts` is the only module that knows `ENGINE_URL` or holds its token. Paths are
  literals written there, never values from a request. The engine takes camelCase and answers in snake_case, and
  `camelize` converts keys only. Engine failures become 502 `ENGINE_*` codes. The request id is forwarded to the
  engine via Hono context storage.
- **Background:** `src/lib/fill-sync.ts` copies simulation fills into Postgres every minute. It's started only from
  `src/index.ts`, so tests never run it.

## Invariants

- **Strategy versions are append-only.** An edit inserts a new `StrategyVersion` row keyed by `specHash`, and an
  unchanged spec returns the current head.
- **Validate specs before storing them.** Use `validateSpec` from `@quant/contracts/spec-validate` for the semantic check
  and return 422 `SPEC_INVALID` with the full error list in `details`.
- **Backtest rows are written before the engine call.** Each carries a `requestId` idempotency key that is reused on
  retry.
- **Simulation `accountId` is minted server-side.** Never accept one from a client.
- **Money stays a decimal string or Prisma `Decimal`.** Never a JS `number`.
