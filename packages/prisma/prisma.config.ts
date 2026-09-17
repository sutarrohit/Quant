import "dotenv/config";
import { defineConfig } from "prisma/config";

// @repo/prisma has no runtime src of its own beyond the generated client, so it reads
// DATABASE_URL directly rather than importing a consumer's env validator. D-10's local compose
// Postgres has no connection pooler, so there is no pooled/direct URL split to carry over either
// — a single DATABASE_URL is the whole contract, for apps/server as much as for engine/.
const databaseUrl = process.env.DATABASE_URL;

export default defineConfig({
  engine: "classic",
  // Resolved relative to THIS file's location (packages/prisma/prisma.config.ts sits inside
  // packages/prisma/, alongside the schema) — probed via `prisma validate`; see
  // packages/prisma/README.md for the resolution-base note.
  schema: "schema.prisma",
  migrations: {
    path: "migrations",
  },
  // `prisma generate` needs no database, and it runs on install and inside the Docker build
  // where no DATABASE_URL exists — so the URL is attached only when it is actually set, rather
  // than throwing here and taking client generation down with it. The migrate commands, which
  // do need it, still fail loudly (from Prisma itself) when it is absent.
  ...(databaseUrl ? { datasource: { url: databaseUrl } } : {}),
});
