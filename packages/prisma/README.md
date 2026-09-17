# @repo/prisma

The repository's Prisma workspace package. Sole schema owner (D-11): no other tool migrates any
table this package declares, and no other package generates a Prisma client.

## Schema ownership: one schema, one owner

`packages/prisma/schema.prisma` is the only Prisma schema in the repository, and this package is
the only thing that migrates the tables it declares. `apps/server` used to carry a second,
divergent `schema.prisma` of its own (the `User` model, plus its own `prisma.config.ts` and
generated client); both copies had converged on the same `User` definition, so the merge that
D-09 deferred to Phase 4 was a deletion — `apps/server` now consumes this package as
`@repo/prisma` instead of generating a client of its own.

## What consumers import

`prisma generate` writes a **TypeScript** client (Prisma 7's `prisma-client` generator emits
`.ts`, not `.js`) into `src/generated/`, which is gitignored. `tsc` then compiles it, together
with the one-line re-export in `src/index.ts`, to `dist/` — so consumers import compiled
JavaScript with declarations and never compile Prisma's output themselves:

```ts
import { PrismaClient } from "@repo/prisma";
```

`pnpm --filter @repo/prisma build` runs both steps, and neither needs a database: `prisma
generate` never reads `datasource.url`, which `prisma.config.ts` exposes as a getter so an absent
`DATABASE_URL` is a problem only for the commands that actually connect.

Two tsconfigs, on purpose. `tsconfig.json` covers the whole package -- `src/` *and*
`prisma.config.ts` -- so the config file is typechecked and editors resolve `process` in it;
`tsconfig.build.json` narrows to `src/` and is what emits, keeping the entry point at
`dist/index.js` rather than `dist/src/index.js`.

Consumers supply their own driver adapter and connection string — this package deliberately owns
no connection. `apps/server` passes `@prisma/adapter-pg` with its validated `DATABASE_URL`; note
that a consumer emitting declarations must annotate the instance (`const prisma: PrismaClient =
...`), or `tsc` reports TS2742 against this package's internal modules.

## Config path resolution (probed, not assumed)

Paths inside `prisma.config.ts` resolve **relative to the config file's location**, not the
directory the CLI is invoked from — per Prisma's own docs, and probed empirically with
`pnpm --filter @repo/prisma exec prisma validate` before being encoded. `prisma.config.ts` sits
next to `schema.prisma` at the package root, so the config-relative form is correct here:

```ts
schema: "schema.prisma",
migrations: { path: "migrations" },
```

A `prisma/`-prefixed form would be correct only for a config file that lives one level *above*
its schema directory, which is not this layout.

## Deliberate ID-default deviation

The three quant models (`Trial`, `SnapshotCapture`, `SymbolListingSnapshot`) generate their `id`
in Postgres itself:

```prisma
id String @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
```

This is **not** the pattern the `User` model uses
(`id String @id @default(uuid())`), and the difference is deliberate, not an oversight — do not
"fix" it to match. `@default(uuid())` generates the value inside the Prisma **client**, so
Postgres itself gets no `DEFAULT` on that column; a bare SQLAlchemy Core `INSERT` from
`engine/persistence/` that omits `id` would violate the `NOT NULL` primary-key constraint under
that pattern. The database-generated default makes the Python-only write path in Task 3 possible
without ever invoking the Prisma client from Python.

Postgres 13+ ships the `pgcrypto`-backed `gen_random_uuid()` function in core — no
`CREATE EXTENSION` statement is required.

## Explicit `@map` on every quant field

Prisma does **not** translate camelCase field names into snake_case columns on its own — the
`User` model above proves it (`privyDid`, `onboardingCompletedAt` stay camelCase in Postgres,
with no `@map` anywhere on them). Every multi-word field on the three quant models carries an
explicit `@map("snake_case_name")` so the physical columns are snake_case, matching the
hand-declared SQLAlchemy Core columns in `engine/persistence/`. `User` keeps its camelCase
columns: it is `apps/server`'s live table, and renaming those columns is a migration of its own,
not a side effect of this one. Everything added since follows the snake_case convention, `wallet`
included — `User` is the exception, not the pattern.

## No deduplication, ever

Neither `SnapshotCapture` nor `SymbolListingSnapshot` carries a unique constraint on
`captureDate`, on `(symbol, capturedAt)`, or any date-truncated column, and neither carries a
`validFrom`/`validTo` range (D-14). A dedup'd table cannot distinguish "the universe did not
change" from "the cron silently died" — which is exactly what the daily gapless-count success
criterion exists to prove. A retry for an already-captured date is recorded as a second `complete`
parent row, visible to the query, rather than rejected at write time.

## The trials guarantee: exact window

`engine/persistence/trials.py`'s `trial_recorder` guarantees a row for **every exit path after
the recorder is entered** — normal completion, an exception raised anywhere inside the guarded
block, and (from plan 01-09) a keyboard interrupt. It does **not** guarantee a row for failures
before that point: a malformed CLI invocation, an unreadable or invalid spec file, or an
unreachable database each fail before a run is identifiable, and by definition have no
`params_hash` to record it under. These are not lost runs — there was no run. The one ceiling
this does not cover is a hard kill (SIGKILL, power loss), which still loses the row; the upgrade
path is write-ahead-then-update, which Phase 8 needs anyway for durable `clientOrderId` lineage.

## Commands

```bash
pnpm --filter @repo/prisma build         # prisma generate + tsc -> dist/ (what consumers import)
pnpm --filter @repo/prisma db:migrate    # local dev migration
pnpm --filter @repo/prisma db:deploy     # apply committed migrations (CI, hosted cron target)
pnpm --filter @repo/prisma db:generate   # regenerate the client
pnpm --filter @repo/prisma exec prisma validate
```

`DATABASE_URL` is read directly from the environment (see `.env.example`);
`packages/prisma/.env` is gitignored by the repository root `.gitignore`.
