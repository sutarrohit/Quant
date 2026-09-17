// The public face of @quant/prisma.
//
// `prisma generate` writes a TypeScript client into src/generated/ (Prisma 7's
// `prisma-client` generator emits .ts, not .js), so this package compiles it to
// dist/ and consumers import the compiled output — apps/server no longer runs
// the generator or compiles Prisma's output itself.
export * from "./generated/client.js";
