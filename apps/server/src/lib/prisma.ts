import { PrismaClient } from "@repo/prisma";
import { PrismaPg } from "@prisma/adapter-pg";
import env from "../env.js";

const adapter = new PrismaPg({ connectionString: env.DATABASE_URL });

// The annotation is load-bearing: this package emits declarations, and the inferred client type
// reaches into @repo/prisma's own internal modules, which tsc refuses to name from here (TS2742).
export const prisma: PrismaClient = new PrismaClient({ adapter });
