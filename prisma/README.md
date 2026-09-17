# @repo/prisma

Standalone Prisma workspace package (D-09). Sole schema owner (D-11) for the whole repository:
no other tool migrates any table this package declares.

## Schema ownership: two divergent files, one authoritative for Phase 1

This repo now holds **two** `schema.prisma` files that will not be reconciled until Phase 4:

- **`prisma/schema.prisma` (this package) — authoritative for Phase 1.** Carries the four
  better-auth models (`User`, `Session`, `Account`, `Verification`, copied verbatim, unmodified)
  plus the three Phase 1 quant tables (`Trial`, `SnapshotCapture`, `SymbolListingSnapshot`).
- **`apps/server/prisma/schema.prisma` — untouched, out of the workspace.** Still backs the
  Hono/Better-Auth runtime in `apps/server`, which is de-listed from `pnpm-workspace.yaml`
  until Phase 4 per D-09.

Phase 4 must **merge** these two files rather than pick one — `apps/server` needs the
better-auth models with its existing runtime wired to them, and this package's quant tables need
to keep being writable from `engine/`. This is a tracked decision, not a surprise to discover
later.

## Config path resolution (probed, not assumed)

`prisma/prisma.config.ts` sits *inside* `prisma/`, one directory level below where
`apps/server/prisma.config.ts` sits relative to its own `prisma/` directory. Per Prisma's own
docs, paths inside `prisma.config.ts` are resolved **relative to the config file's location**,
not the directory the CLI is invoked from. That means the config-relative form is correct here:

```ts
schema: "schema.prisma",
migrations: { path: "migrations" },
```

not the `prisma/`-prefixed form `apps/server/prisma.config.ts` uses (which is correct *there*
only because that config file lives one level above its own `prisma/` directory). This was
probed empirically — `pnpm --filter @repo/prisma exec prisma validate` — before being encoded,
per this plan's instruction not to copy the source config's path values on faith. The probe
passed on the first (config-relative) form; no fallback to the prefixed form was needed.

## Deliberate ID-default deviation

The three new models (`Trial`, `SnapshotCapture`, `SymbolListingSnapshot`) generate their `id`
in Postgres itself:

```prisma
id String @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
```

This is **not** the pattern the four existing better-auth models use
(`id String @id @default(uuid())`), and the difference is deliberate, not an oversight — do not
"fix" it to match. `@default(uuid())` generates the value inside the Prisma **client**, so
Postgres itself gets no `DEFAULT` on that column; a bare SQLAlchemy Core `INSERT` from
`engine/persistence/` that omits `id` would violate the `NOT NULL` primary-key constraint under
that pattern. The database-generated default makes the Python-only write path in Task 3 possible
without ever invoking the Prisma client from Python.

Postgres 13+ ships the `pgcrypto`-backed `gen_random_uuid()` function in core — no
`CREATE EXTENSION` statement is required.

## Explicit `@map` on every new field

Prisma does **not** translate camelCase field names into snake_case columns on its own — the
four better-auth models above prove it (`emailVerified`, `accessTokenExpiresAt` stay camelCase in
Postgres, with no `@map` anywhere on them). Every multi-word field on the three new models
carries an explicit `@map("snake_case_name")` so the physical columns are snake_case, matching
the hand-declared SQLAlchemy Core columns in `engine/persistence/`. The four better-auth models
were left untouched — renaming their columns is a Phase 4 concern, not this plan's.

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
pnpm --filter @repo/prisma db:migrate    # local dev migration
pnpm --filter @repo/prisma db:deploy     # apply committed migrations (CI, hosted cron target)
pnpm --filter @repo/prisma db:generate   # regenerate the client
pnpm --filter @repo/prisma exec prisma validate
```

`DATABASE_URL` is read directly from the environment (see `.env.example`); `prisma/.env` is
gitignored by the repository root `.gitignore`.
