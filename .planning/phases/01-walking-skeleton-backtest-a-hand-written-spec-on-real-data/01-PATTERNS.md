# Phase 1: Walking Skeleton — Pattern Map

**Mapped:** 2026-09-06
**Files analyzed:** 13 (new/modified)
**Analogs found:** 6 real / 13 (rest have no in-repo analog — new domain per D-01)

## Ground truth on this repo

This is an **unmodified Turborepo template**: `apps/server` (Hono/Prisma API, better-auth
domain), `apps/web` (Next.js), `packages/fastapi-server` (a `fastapi-blog` template, being
gutted per D-03), `packages/eslint-config`, `packages/typescript-config`. No `.github/workflows`
exist. No Postgres service exists in either docker-compose file today — both simply build an
app image and expect "bring your own Postgres" via `DATABASE_URL`/`DIRECT_URL` in `.env`. The
Nautilus v2 submodule checkout at `/Users/criox4/Codes/Trade_Platform/Nautilus_Engine /nautilus_trader`
is **outside this repo's working tree** (not a git submodule of `quant-platform` yet — D-04 has
not landed) — its example strategies are real, verified code (per 01-RESEARCH.md, which already
cites exact paths and line numbers there), but they are not `git ls-files`-tracked inside
`quant-platform` and cannot be cited as in-repo analogs until the submodule is added. Treat
RESEARCH.md's own Nautilus citations (`docs/getting_started/backtest_high_level.py`,
`docs/tutorials/ema_cross.py`, `python/nautilus_trader/testkit/providers.py:562-599`) as the
reference for `engine/adapters/dsl_strategy.py` and the CLI runner — there is nothing better
in-tree to copy from for those two files.

**Almost everything under `engine/` (D-02) has no in-repo analog.** This is expected and stated
plainly rather than forced into a weak match — say so per file below.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `engine/pyproject.toml` | config | — | `packages/fastapi-server/pyproject.toml` | role-match (toolchain shape only; deps differ entirely) |
| `engine/package.json` (turbo shim) | config | — | `packages/fastapi-server/package.json` | role-match |
| `prisma/schema.prisma` (extracted package, D-09) | model/migration | CRUD | `apps/server/prisma/schema.prisma` | exact (same tool, same file type — but see ID-default gotcha below) |
| `prisma/prisma.config.ts` | config | — | `apps/server/prisma.config.ts` | exact |
| `turbo.json` (add `engine` tasks) | config | — | `turbo.json` (this repo's own, to be edited) | exact — this is a modify, not a new-analog case |
| `pnpm-workspace.yaml` (drop apps/web, apps/server per D-09; keep prisma pkg) | config | — | `pnpm-workspace.yaml` (own file, to be edited) | exact |
| `package.json` (root, rename off "template", D-08 pipeline) | config | — | `package.json` (own file, to be edited) | exact |
| `docker-compose.yml` (root, single Postgres, D-10) | config | — | `apps/server/docker-compose.yml` + `packages/fastapi-server/docker-compose.yml` | partial — neither ships a Postgres service; the "single service, bring-your-own-env" *shape* is the only reusable part |
| `engine/dsl/spec.py`, `engine/dsl/evaluator.py` | model / service | transform (pure) | none in-repo | no analog — new domain (D-02); see RESEARCH.md Pattern 2 |
| `engine/adapters/dsl_strategy.py` | service | event-driven | none in-repo (Nautilus submodule not yet checked out as tracked source) | no analog — cite RESEARCH.md Architecture Pattern 2 (`docs/tutorials/ema_cross.py` in the untracked Nautilus checkout) as the reference shape instead |
| `engine/data/binance_vision.py` | service | file-I/O / batch | none in-repo | no analog — new domain; RESEARCH.md Pattern 3 is the reference |
| `engine/data/exchange_info.py` | service | CRUD (daily snapshot write) | none in-repo | no analog — new domain |
| `engine/cli/backtest.py` | controller (CLI entry point) | request-response (batch) | none in-repo — `packages/fastapi-server/main.py` is the closest *role* match (an app entry point) but wrong data flow (HTTP, not CLI) | weak — do not force it; write fresh per D-17/RESEARCH.md |
| `engine/persistence/trials.py` | model (SQLAlchemy Core `Table()`) | CRUD | none in-repo — `apps/server/prisma/schema.prisma` is the schema *source* it must mirror, but there is no existing SQLAlchemy Core file in this repo to copy structure from | no code analog; mirror Prisma's column list per RESEARCH.md Pattern 4 |
| `docs/adr/0001-shelve-tenancy-patch.md` | doc | — | none in-repo (no `docs/adr/` dir yet) | no analog — new domain, D-05 |

## Pattern Assignments

### `engine/pyproject.toml` (config)

**Analog:** `packages/fastapi-server/pyproject.toml` (full file, 34 lines — read in one pass above)

Copy the **toolchain shape**, not the dependencies — every dependency in the source file
(`aiosqlite`, `alembic`, `fastapi`, `pwdlib`, `pyjwt`) belongs to the blog domain D-03 strips out
and has zero relevance to `engine/`.

**Python/ruff/pytest config to copy verbatim (shape only):**
```toml
[project]
name = "engine"
version = "0.1.0"
requires-python = ">=3.13"

[tool.pytest.ini_options]
testpaths = ["tests"]
filterwarnings = ["ignore::DeprecationWarning"]

[tool.ruff]
line-length = 120
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "C4"]
ignore = ["E501"]
```
Source pins `requires-python = ">=3.13"` and ruff `target-version = "py313"` — RESEARCH.md
confirms this is compatible with the Nautilus submodule's own `>=3.12,<3.15` floor, so no change
needed there. Do **not** copy the `[tool.ruff.lint.per-file-ignores]` `alembic/*` line — there is
no alembic in `engine/`.

**Real deps for `engine/` come from RESEARCH.md's Standard Stack table** (`nautilus_trader`
editable submodule, `pydantic`, `sqlalchemy`, `pyarrow`, `datamodel-code-generator` as dev dep) —
not from the fastapi-server analog.

---

### `engine/package.json` (turbo shim, D-02)

**Analog:** `packages/fastapi-server/package.json` (full file, 18 lines — read above)

This IS a near-exact structural match — a Python package that joins the turbo graph via a thin
`package.json` whose scripts shell out to `uv run`.

**Pattern to copy (scripts block), stripped of blog-specific `db:*` scripts (D-11 puts migrations
in the Prisma package, not here):**
```json
{
  "name": "@repo/engine",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "lint": "uv run ruff check .",
    "check-types": "uv run ruff check --select F .",
    "test": "uv run pytest",
    "build": "uv sync --frozen"
  }
}
```
Source's `"check-types": "uv run ruff check --select F ."` is the existing repo convention for
faking a Python "check-types" turbo task (ruff has no real type checker wired here) — reuse this
exact convention rather than inventing a mypy/pyright step D-08 doesn't ask for.

---

### `prisma/schema.prisma` (extracted package, D-09/D-11) — the highest-stakes analog in this phase

**Analog:** `apps/server/prisma/schema.prisma` (full file, 74 lines — read above)

**Datasource + generator block to copy verbatim (lines 1-8 of source):**
```prisma
datasource db {
  provider = "postgresql"
}

generator client {
  provider = "prisma-client"
  output   = "./generated"
}
```

**CRITICAL — do NOT copy the source's ID-default pattern.** Every existing model
(`User`, `Session`, `Account`, `Verification`) uses:
```prisma
id String @id @default(uuid())
```
RESEARCH.md's Pattern 4 (verified against prisma.io docs) establishes this generates the UUID in
the **Prisma Client**, not in Postgres — a bare SQLAlchemy Core `INSERT` from `engine/persistence/trials.py`
that omits `id` will violate the `NOT NULL` primary-key constraint, since Postgres itself has no
`DEFAULT` for that column under `@default(uuid())`. The two new Phase 1 models must instead use:
```prisma
model Trial {
  id String @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  // ... VALID-01 fields per D-15
  ranAt DateTime @default(now())   // safe to omit from the Python INSERT — this one IS a real SQL DEFAULT
  @@map("trials")
}

model SymbolListingSnapshot {
  id String @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  // ... raw payload + extracted columns per D-13
  capturedAt DateTime @default(now())
  @@map("symbol_listing_snapshot")
}
```
This is a **deliberate deviation** from the existing repo convention, not an oversight — call it
out explicitly in the plan/PR so a reviewer doesn't "fix" it back to `@default(uuid())` to match
the other four models.

**Conventions to keep matching the source:** `@@map(...)` snake_case table names,
`@@index([...])` on frequently-queried columns, `camelCase` Prisma field names mapped to
snake_case columns implicitly by Prisma's default behavior (the source relies on this — no
explicit `@map` per field anywhere in the file).

---

### `prisma/prisma.config.ts`

**Analog:** `apps/server/prisma.config.ts` (full file, 21 lines — read above)

**Pattern to copy nearly verbatim** — only the env-loading import path and the error message
change:
```typescript
import "dotenv/config";
import { defineConfig } from "prisma/config";
import env from "./src/env.js";   // ADAPT: this file needs its own env module or a simpler
                                    // process.env read, since the extracted prisma/ package
                                    // (D-09) has no src/ directory of its own yet

const directUrl = env.DIRECT_URL;
if (!directUrl) throw new Error("DIRECT_URL is required in prisma/.env");

export default defineConfig({
  engine: "classic",
  schema: "prisma/schema.prisma",
  migrations: { path: "prisma/migrations" },
  datasource: { url: directUrl, directUrl },
});
```
Note the source requires **both** `DIRECT_URL` and a derived pooled `url` — confirm at
implementation time whether the extracted package needs the pooled/direct split at all (D-10's
single local compose Postgres has no pooler), or whether a single `DATABASE_URL` suffices and
this file can be simplified further (ponytail: don't carry over a pooling concern the local-dev
Postgres doesn't have).

---

### `turbo.json`, `pnpm-workspace.yaml`, root `package.json` (D-08 pipeline)

**Analog:** the repo's own current files (read in full above) — this is a **modify**, not a
copy-from-elsewhere case.

**Current `turbo.json` task shape to extend** (lines full file):
```json
{
  "tasks": {
    "lint": { "dependsOn": ["^lint"] },
    "check-types": { "dependsOn": ["^check-types"] },
    "test": { "dependsOn": ["^build"], "outputs": [] }
  }
}
```
D-08's `turbo run test lint check-types` pipeline already works unmodified once `engine/package.json`
(above) exposes matching script names — **no new turbo.json task definitions are needed**, only
the workspace member list changes. This is the ponytail-lazy read: the task graph is
role-agnostic (`^lint`/`^build` dependency wiring works identically for a Python package with a
`package.json` shim), so D-08 is satisfied by adding `engine` and `prisma` to
`pnpm-workspace.yaml`'s `packages:` list, not by writing new turbo config.

**`pnpm-workspace.yaml` — current (2 lines) → target per D-09:**
```yaml
packages:
  - "apps/*"      # REMOVE per D-09 (apps/web, apps/server go until Phase 4)
  - "packages/*"  # KEEP (fastapi-server, eslint-config, typescript-config)
```
becomes:
```yaml
packages:
  - "packages/*"
  - "engine"
  - "prisma"
```

**Root `package.json`** — rename `"name": "template"` → the real project name; scripts block
(`build`/`dev`/`lint`/`check-types`/`test` → `turbo run ...`) is already exactly D-08's shape and
needs no structural change, only the `name` field and confirming `engine`/`prisma` are pulled in
via the workspace list above.

---

### `docker-compose.yml` (root, single Postgres, D-10)

**Analogs:** `apps/server/docker-compose.yml` and `packages/fastapi-server/docker-compose.yml`
(both full files, read above) — **partial match only**. Neither file defines a Postgres
`services:` entry; both are "build one app image, `env_file: .env`, bring your own external
Postgres" — the opposite of D-10's requirement (Postgres *owned* by this compose file).

**Reusable shape (env-file convention, restart policy):**
```yaml
services:
  api:
    build: { context: ..., dockerfile: ... }
    restart: unless-stopped
    env_file: .env
```
**Not reusable / must be written fresh:** the actual `postgres:` service block, volume for data
persistence, and `POSTGRES_*` env vars — there is no existing example of this repo running its
own Postgres container. Use the official `postgres:16` (or newer LTS) image with a named volume
as a standard, un-analog'd addition — this is boilerplate that doesn't need an in-repo precedent.

---

### `engine/dsl/`, `engine/adapters/`, `engine/data/`, `engine/cli/`, `engine/persistence/`

**No in-repo analog for any of these five.** This is the expected, stated outcome for D-02's new
`engine/` tree — forcing a match to `packages/fastapi-server`'s routers/service/schema layout
would be misleading, since that package is an HTTP CRUD blog API (request-response over
FastAPI routers) and every one of these five files is either pure-Python (no I/O at all),
file/S3 I/O, or a CLI entry point — structurally unrelated data flows.

For these five, RESEARCH.md's own **Architecture Patterns 1-4** and **Code Examples** section
(already containing verified, cited excerpts from the pinned Nautilus v2 checkout and official
docs) are the reference material — reuse RESEARCH.md directly rather than re-deriving weaker
excerpts here. Specifically:
- `engine/adapters/dsl_strategy.py` → RESEARCH.md Pattern 2 (`Strategy` lifecycle, verified
  against `docs/tutorials/ema_cross.py` in the untracked Nautilus checkout).
- `engine/data/binance_vision.py` → RESEARCH.md Pattern 3 (`Bar` construction from CSV rows,
  verified against `python/nautilus_trader/testkit/providers.py:562-599`) plus Pitfall 1
  (timestamp-unit detection).
- `engine/cli/backtest.py` → RESEARCH.md Pattern 1 (`BacktestNode`/`BacktestRunConfig`, verified
  against `docs/getting_started/backtest_high_level.py`).
- `engine/persistence/trials.py` → RESEARCH.md Pattern 4 (SQLAlchemy Core `Table()` mirroring
  Prisma, with the `gen_random_uuid()` fix already worked into the schema section above).

## Shared Patterns

### uv + ruff + pytest toolchain shape
**Source:** `packages/fastapi-server/pyproject.toml` + `packages/fastapi-server/package.json`
**Apply to:** `engine/pyproject.toml`, `engine/package.json` — copy the config shape (ruff rules,
line-length, pytest `testpaths`, the `package.json`-as-turbo-shim idiom), discard every actual
dependency (blog domain, D-03).

### Prisma-as-sole-schema-owner, with ID-default deviation
**Source:** `apps/server/prisma/schema.prisma`, `apps/server/prisma.config.ts`
**Apply to:** `prisma/schema.prisma`, `prisma/prisma.config.ts` — copy datasource/generator
blocks and `@@map`/`@@index` conventions verbatim; **deviate deliberately** on `@id` default per
RESEARCH.md Pattern 4 (`dbgenerated("gen_random_uuid()")` not `@default(uuid())`) for the two new
tables only — do not touch the four existing better-auth models' ID pattern.

### turbo task graph is already D-08-shaped
**Source:** `turbo.json` (this repo, unmodified)
**Apply to:** no new task definitions needed — `engine` and `prisma` joining
`pnpm-workspace.yaml` is the only required change, since `^lint`/`^build`/`test` dependency
wiring is already generic across package types.

### "bring your own env" compose convention
**Source:** `apps/server/docker-compose.yml`, `packages/fastapi-server/docker-compose.yml`
**Apply to:** root `docker-compose.yml`'s non-Postgres services only (env_file + restart
policy convention); the Postgres service itself has no in-repo precedent and must be written
fresh.

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `engine/dsl/spec.py` | model | transform | New pure-Python domain (D-02); zero existing Python beyond the fastapi-blog template, which is being stripped anyway (D-03) |
| `engine/dsl/evaluator.py` | service | transform | Same — no existing indicator/evaluator code anywhere in repo |
| `engine/adapters/dsl_strategy.py` | service | event-driven | Nautilus submodule not yet checked out as tracked source in this repo (D-04 pending); use RESEARCH.md's cited excerpts from the untracked checkout as the reference instead of naming an in-repo path |
| `engine/data/binance_vision.py` | service | file-I/O/batch | No ingestion code of any kind exists in this repo today |
| `engine/data/exchange_info.py` | service | CRUD | Same — no daily-snapshot or cron-writer code exists |
| `engine/cli/backtest.py` | controller | request-response(batch) | No CLI entry point exists anywhere in this repo (both apps are HTTP servers / a web app) |
| `engine/persistence/trials.py` | model | CRUD | No SQLAlchemy Core file exists in this repo (both DB-touching packages use an ORM — Prisma client / SQLAlchemy... actually fastapi-server likely uses SQLAlchemy ORM, not Core — either way, no Core `Table()`-mirrors-external-schema pattern exists) |
| `docs/adr/0001-shelve-tenancy-patch.md` | doc | — | No `docs/adr/` directory exists yet; this is a new documentation convention for the repo |
| `.github/workflows/*.yml` (D-12 daily cron, D-08 CI) | config | event-driven (scheduled) | No `.github/workflows/` directory exists in this repo at all — CI/cron patterns must be written from scratch, not adapted |
| `.devcontainer/*` (D-10) | config | — | No devcontainer exists in this repo |

## Metadata

**Analog search scope:** full repo tree (`apps/`, `packages/`, root config files); confirmed via
`git ls-files` that all cited analog paths are tracked source, not gitignored mirrors. The
Nautilus v2 checkout at `/Users/criox4/Codes/Trade_Platform/Nautilus_Engine /nautilus_trader` was
checked and confirmed to sit **outside** the `quant-platform` git working tree entirely — it is
not tracked by this repo's git index at all (not even as a gitignored mirror), so it is correctly
excluded from in-repo analog citations here; RESEARCH.md's own citations into it stand as the
reference instead.
**Files scanned:** all files under `apps/server/`, `packages/fastapi-server/`, root config
(`turbo.json`, `pnpm-workspace.yaml`, `package.json`, both `docker-compose.yml` files,
`prisma.config.ts`, `schema.prisma`).
**Pattern extraction date:** 2026-09-06
