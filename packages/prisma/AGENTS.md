# AGENTS.md — packages/prisma (`@quant/prisma`)

Guidance for any coding agent working in `packages/prisma`. `CLAUDE.md` imports this file. The root `AGENTS.md`
(working agreement, monorepo layout) applies too.

## Commands

```bash
pnpm --filter @quant/prisma build          # prisma generate + tsc -> dist/ (also runs on pnpm install)
pnpm --filter @quant/prisma db:migrate     # prisma migrate dev; creates a migration from schema changes
pnpm --filter @quant/prisma db:deploy      # apply committed migrations
pnpm --filter @quant/prisma exec prisma validate
```

`DATABASE_URL` comes from `packages/prisma/.env` (copy `.env.example`) and is used only by the CLI. Generating the
client needs no database. The runtime connection is `apps/server`'s own `DATABASE_URL`.

## What this package is

- **The only Prisma schema and the only migrator** in the repo. `apps/server` imports the compiled client
  (`import { PrismaClient } from '@quant/prisma'`) and supplies its own `@prisma/adapter-pg` connection. No other
  package generates a client.
- Prisma 7's `prisma-client` generator emits TypeScript into `src/generated/` (gitignored). `tsc -p
  tsconfig.build.json` compiles it to `dist/`. After any schema change, run `build` or consumers keep stale types.
- Migrations in `migrations/` are committed and never edited once applied. Change the schema, then run `db:migrate`.

## Schema conventions

- `User` is the exception: camelCase columns, no `@map`, and `@default(uuid())`. Leave it as it is.
- Every other model uses `@default(dbgenerated("gen_random_uuid()")) @db.Uuid` ids, an explicit
  `@map("snake_case")` on every multi-word field, and `@@map("snake_case_table")`. New models follow this pattern.
- Money and fee fields are `Decimal @db.Decimal(38, 18)`, never `Float`.
- `StrategyVersion` rows are immutable. An edit is a new row.
- `StrategyVersion.spec` stores the engine's camelCase JSON byte for byte.
- `AccountFill` is keyed `(accountId, tradeId)` so re-copying a fill is idempotent.

## Stale docs

`README.md` still describes the earlier phase-01 design: `Trial`/`SnapshotCapture`/`SymbolListingSnapshot` models and
Python writing through `engine/persistence/`. Those models no longer exist. Trust `schema.prisma` over the README.
