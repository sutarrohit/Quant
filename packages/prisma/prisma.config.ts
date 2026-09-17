import "dotenv/config";
import { defineConfig } from "prisma/config";

// @quant/prisma has no runtime src of its own beyond the generated client, so it reads
// DATABASE_URL directly rather than importing a consumer's env validator. D-10's local compose
// Postgres has no connection pooler, so there is no pooled/direct URL split to carry over either
// — a single DATABASE_URL is the whole contract, for apps/server as much as for engine/.
const databaseUrl = process.env.DATABASE_URL;

export default defineConfig({
  // No `engine` key: Prisma 7.10's config schema has no such option (@prisma/config
  // does not mention it, and the CLI silently ignores unknown keys), so the
  // `engine: "classic"` this file used to carry was doing nothing. It only became
  // visible once tsconfig.json started typechecking this file.
  //
  // Resolved relative to THIS file's location (packages/prisma/prisma.config.ts sits inside
  // packages/prisma/, alongside the schema) — probed via `prisma validate`; see
  // packages/prisma/README.md for the resolution-base note.
  schema: "schema.prisma",
  migrations: {
    path: "migrations",
  },
  // `prisma generate` needs no database, and it runs on install and inside the Docker build
  // where no DATABASE_URL exists. A getter rather than a plain value so that stays true: the
  // URL is read only by the commands that actually connect, and those get a message naming
  // the file to create rather than Prisma's generic "datasource.url property is required".
  datasource: {
    get url() {
      if (!databaseUrl) {
        throw new Error(
          'DATABASE_URL is required for this command. Copy packages/prisma/.env.example to packages/prisma/.env.'
        );
      }

      return databaseUrl;
    },
  },
});
