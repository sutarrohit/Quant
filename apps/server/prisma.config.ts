import "dotenv/config";
import { defineConfig } from "prisma/config";

import env from "./src/env.js";

const directUrl = env.DIRECT_URL;

if (!directUrl) throw new Error("DIRECT_URL is required in apps/api/.env");

export default defineConfig({
  engine: "classic",
  schema: "prisma/schema.prisma",
  migrations: {
    path: "prisma/migrations"
  },
  datasource: {
    url: directUrl,
    directUrl
  }
});
