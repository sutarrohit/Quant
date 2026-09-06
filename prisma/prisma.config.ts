import "dotenv/config";
import { defineConfig } from "prisma/config";

// The extracted @repo/prisma package (D-09) has no src/ directory of its own, so this reads
// DATABASE_URL directly rather than importing apps/server's ./src/env.js. D-10's local compose
// Postgres has no connection pooler, so there is no pooled/direct URL split to carry over either
// — a single DATABASE_URL is the whole contract.
const databaseUrl = process.env.DATABASE_URL;

if (!databaseUrl) throw new Error("DATABASE_URL is required in prisma/.env");

export default defineConfig({
  engine: "classic",
  // Resolved relative to THIS file's location (prisma/prisma.config.ts sits inside prisma/,
  // one level below where apps/server/prisma.config.ts sits) — probed via `prisma validate`;
  // see prisma/README.md for the resolution-base note.
  schema: "schema.prisma",
  migrations: {
    path: "migrations",
  },
  datasource: {
    url: databaseUrl,
  },
});
