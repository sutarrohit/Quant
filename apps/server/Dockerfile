# syntax=docker/dockerfile:1
#
# Hono API (@quant/api) — multi-stage build.
#
# IMPORTANT: the build context is the repository ROOT, not apps/server,
# because this is a pnpm workspace and the package depends on @quant/* configs.
# apps/server/docker-compose.yml sets `context: ../..` accordingly.
#
# Stages:
#   base       node + openssl + pnpm, shared by every other stage
#   deps       full install (incl. dev) from manifests only -- cached until a
#              package.json or the lockfile changes
#   build      prisma generate + tsc, then `pnpm deploy` to collect a
#              self-contained prod tree for this package alone
#   runtime    that tree only, running as a non-root user

# ------------------------------------------------------------------- base
FROM node:20-slim AS base

# OpenSSL + CA certs are required by Prisma's query engine at runtime.
RUN apt-get update \
  && apt-get install -y --no-install-recommends openssl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# pnpm 10 via corepack (pinned by `packageManager` in package.json).
ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH
RUN corepack enable && corepack prepare pnpm@10.34.5 --activate

WORKDIR /repo


# ------------------------------------------------------------------- deps
# Only manifests are copied, so this layer survives every source-only change.
# Every workspace member listed in pnpm-workspace.yaml needs its package.json
# present for --frozen-lockfile to validate.
FROM base AS deps

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/server/package.json apps/server/
COPY packages/prisma/package.json packages/prisma/
COPY packages/eslint-config/package.json packages/eslint-config/
COPY packages/typescript-config/package.json packages/typescript-config/
COPY packages/fastapi-server/package.json packages/fastapi-server/
COPY engine/package.json engine/
COPY schemas/package.json schemas/

# @quant/prisma generates and compiles its client in a postinstall, so its schema,
# config and entrypoint must be in the context before the install -- everything
# else stays source-only, and this layer still survives an app-source change.
COPY packages/prisma/schema.prisma packages/prisma/prisma.config.ts packages/prisma/tsconfig.json packages/prisma/
COPY packages/prisma/src/index.ts packages/prisma/src/

# The trailing "..." also installs the workspace packages @quant/api depends on.
#
# pnpm 10 does not run dependency lifecycle scripts unless the package is listed
# in `pnpm.onlyBuiltDependencies` at the workspace root -- @prisma/engines and
# prisma are there, without which the `prisma generate` below has no query engine.
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile --filter @quant/api...


# ------------------------------------------------------------------ build
FROM deps AS build

COPY apps/server apps/server
COPY packages/prisma packages/prisma
COPY packages/typescript-config packages/typescript-config

# @quant/prisma is built first (prisma generate + tsc): @quant/api imports the
# compiled client from it and no longer generates one of its own. Neither step
# touches a database, and @quant/api's env validator runs at runtime rather than
# build time, so no placeholder configuration is needed here -- the runtime image
# gets its real configuration from the environment, failing loudly if one is absent.
RUN pnpm --filter @quant/prisma build \
    && pnpm --filter @quant/api build

# Collect @quant/api plus only its production dependencies into one self-contained
# directory with a real (non-symlinked) node_modules.
#
# What lands here is decided by apps/server/package.json, not by this file:
# `--prod` drops devDependencies, and the `files` field limits the copied sources
# to dist/ -- so test and tooling files stay out of the image. @quant/prisma comes
# along as a production dependency, carrying its own dist/ (the generated client).
#
# --legacy is required, not optional: from pnpm 10 a plain `deploy` refuses any
# workspace without `inject-workspace-packages=true`
# (ERR_PNPM_DEPLOY_NONINJECTED_WORKSPACE). It selects the resolver, not the
# output size.
RUN pnpm --filter @quant/api --prod deploy --legacy /prod/api


# ---------------------------------------------------------------- runtime
FROM base AS runtime

WORKDIR /app

COPY --from=build --chown=node:node /prod/api /app

USER node
EXPOSE 4000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:4000/doc').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

# rootDir "." in tsconfig emits the entry to dist/src/index.js (NOT dist/index.js).
CMD ["node", "dist/src/index.js"]
