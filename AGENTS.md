# AGENTS.md

Guidance for any coding agent (Claude Code, Codex, etc.) working in this repository. `CLAUDE.md` imports this file.

## What this is

A quant trading platform: users author strategies as a JSON DSL spec, backtest them, and run paper-trading
simulations. pnpm + Turborepo monorepo, TypeScript front/back, Python engine around NautilusTrader.

The root `README.md` is untouched Turborepo boilerplate — ignore it.

## Working agreement

Applies to every coding agent, including subagents.

- **Stop for review when done.** Once a task is finished, report what changed and wait for the repo owner's review.
  Don't start follow-up work.
- **Never commit unless explicitly told.** No `git commit`, branch, push or PR until the repo owner says so and names
  where the work goes (which branch or PR). Then commit only the work they named.

## Per-package guidance

`apps/web`, `apps/server`, `packages/prisma` and `packages/engine_server` each have their own `AGENTS.md`, with a
`CLAUDE.md` next to it that just imports it (`@AGENTS.md`). Read the package's file before working there. Edit
`AGENTS.md` only, never the `CLAUDE.md` stub.

## Layout and request flow

```
apps/web (Next.js 16, :3000) --/api/v1/* rewrite--> apps/server (Hono, :4000) --bearer--> packages/engine_server (FastAPI, :8000)
                                                         |                                        |
                                                   Postgres (Prisma)                     2x Redis + Parquet catalog
```

| Package | Name | Role |
|---|---|---|
| `apps/web` | `@quant/web` | Next.js App Router UI. Privy auth, TanStack Query, zustand, shadcn/base-ui, Tailwind 4, recharts |
| `apps/server` | `@quant/api` | Hono + `@hono/zod-openapi` API. Owns users, ownership checks, and all Postgres writes |
| `packages/contracts` | `@quant/contracts` | Shared zod schemas for the strategy spec and every API body |
| `packages/prisma` | `@quant/prisma` | Sole Prisma schema/migrations owner; builds a compiled client to `dist/` |
| `packages/engine_server` | (Python, uv) | NautilusTrader service: data catalog, backtest queue worker, live/simulation runtime |

**Legacy, not on the live path:** `engine/` (`@quant/engine`), `schemas/` (`@quant/schemas`), `vendor/nautilus_trader`
(git submodule), `.planning/`, and root `docs/adr/`. These are from an earlier phase-01 design (Nautilus v2 built from
the submodule, Python writing Postgres via SQLAlchemy). The running engine is `packages/engine_server`, and
`apps/server` talks to it via `ENGINE_URL`. `engine/`'s `build` is `uv sync --frozen` against the submodule, so prefer
`--filter` over bare root `pnpm build`/`pnpm test`.

## Commands

Root (Turbo fans out to every workspace package):

```bash
pnpm install              # also runs postinstall: builds @quant/prisma and @quant/contracts into dist/
pnpm dev | build | lint | check-types | test
pnpm format               # prettier (single quotes, width 120, es5 trailing commas)
docker compose up -d      # local Postgres 17 (quant/quant/quant on :5432)
```

Per package:

```bash
pnpm --filter @quant/api dev                       # tsx watch; Swagger UI at http://localhost:4000/docs
pnpm --filter @quant/api test                      # vitest run
pnpm --filter @quant/api exec vitest run tests/unit/spec-hash.test.ts   # single test file
pnpm --filter @quant/api exec vitest run -t "name" # single test by name
pnpm --filter @quant/api db:seed                   # db:seed:reset to wipe first
pnpm --filter @quant/web dev
pnpm --filter @quant/prisma db:migrate             # migrate dev; db:deploy applies committed migrations
pnpm --filter @quant/contracts build               # rebuild after editing contracts — consumers import dist/
```

Engine service (run from `packages/engine_server`; needs Redis on 6379 **and** a separate instance on 6380):

```bash
uv sync
uv run pytest                                   # uv run pytest tests/path/test_x.py::test_name for one
uv run ruff check . && uv run mypy src
uv run fastapi dev src/engine/api/app.py --port 8000
uv run arq engine.worker.main.WorkerSettings    # backtest worker
docker compose up --build                       # api + worker + both Redis instances
```

Env: copy each package's `.env.example` (`apps/server`, `apps/web`, `packages/prisma`, `packages/engine_server`).
`apps/server`'s `ENGINE_INTERNAL_API_KEY` must equal the engine's `NT_INTERNAL_API_KEY`; `PRIVY_APP_ID` must match the
web app's `NEXT_PUBLIC_PRIVY_APP_ID`.

## Architecture notes

**`packages/contracts` is the shared contract.** Server validates requests with it, web builds forms from it. It mirrors
the engine's Pydantic models (`packages/engine_server/src/engine/types/dsl.py`) and semantic validator field for field;
the engine stays authoritative. Changing the DSL means changing both sides. No barrel — import by subpath
(`@quant/contracts/spec`, `/strategy`, `/backtest`, …). It uses plain `zod`, never `@hono/zod-openapi`, so `apps/web`
never pulls in Hono. Both `contracts` and `prisma` are consumed as compiled `dist/`, so rebuild them after edits.

**Server (`apps/server/src`)** — each resource in `routes/<name>/` is a triplet: `*.route.ts` (OpenAPI `createRoute`
using contract schemas), `*.handler.ts` (`AppRouteHandler`), `*.index.ts` (chains `.openapi(route, handler)`, applies
`requireAuth`). Routers are mounted in `src/app.ts`. Business logic lives in `services/`, instantiated as singletons in
`lib/container.ts`. Throw `ApiError(status, code, message, details)` — error `code`s are what the web branches on.
`lib/engine-client.ts` wraps all engine calls and forwards the request id (via Hono context storage). `lib/fill-sync.ts`
polls simulation fills into Postgres every minute (started only from `index.ts`). Every service read filters by
`userId` — the engine has no notion of users. Strategy versions are append-only and keyed by `specHash`.

**Web (`apps/web`)** — calls go to relative `/api/v1/*`, rewritten in `next.config.ts` to the server so the
`privy-token` cookie is same-origin. `utils/request.ts` also sends a bearer token. Per resource: `lib/api/<name>/*-apis.ts`
(one fetch function per server route) and `*-queries.ts` (query-key factory + `queryOptions`/`mutationOptions`).
`proxy.ts` is a UX-only cookie-presence redirect for `(protected)` routes; real auth is `requireAuth` on the API.

**Prisma** — `User` keeps camelCase columns; every other model uses `@map` to snake_case columns. Don't "fix" either.

**Engine service** has its own `packages/engine_server/AGENTS.md` with hard rules (no generated strategy code, no
Postgres, `Decimal` money, determinism, live trading gated off, one step per session). Read it before touching that
package; `docs/nautilus-service-spec.md` there is its source of truth.
