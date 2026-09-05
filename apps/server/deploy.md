# Deploying the API Server to AWS Lambda

This guide explains how to deploy the `@repo/api` Hono backend to **AWS Lambda** using **AWS CDK** (Cloud Development Kit). The deployment uses a **Lambda Function URL** — no API Gateway required.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
- [Step-by-Step Deployment](#step-by-step-deployment)
  - [1. Install AWS CLI](#1-install-aws-cli)
  - [2. Configure AWS Credentials](#2-configure-aws-credentials)
  - [3. Create Production Environment File](#3-create-production-environment-file)
  - [4. Bootstrap CDK (First Time Only)](#4-bootstrap-cdk-first-time-only)
  - [5. Preview Changes (Optional)](#5-preview-changes-optional)
  - [6. Deploy](#6-deploy)
- [CDK Commands Reference](#cdk-commands-reference)
- [Updating the Deployment](#updating-the-deployment)
- [Environment Variables](#environment-variables)
- [Customizing the Lambda](#customizing-the-lambda)
- [Tearing Down](#tearing-down)
- [Troubleshooting](#troubleshooting)
- [Local Development (Unchanged)](#local-development-unchanged)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│                    src/app.ts                        │
│              (Shared Hono Application)               │
│   Routes, Middleware, OpenAPI, CORS, Rate Limiting   │
└────────────┬─────────────────────┬───────────────────┘
             │                     │
      ┌──────▼──────────┐  ┌──────▼──────────┐
      │ src/index.ts     │  │ lambda/index.ts  │
      │ (@hono/node-srv) │  │ (AWS Lambda)     │
      │ Local Dev        │  │ hono/aws-lambda  │
      └──────────────────┘  └──────┬───────────┘
                                   │
                            ┌──────▼──────────┐
                            │ infra/stack.ts   │
                            │ (CDK Stack)      │
                            │ NodejsFunction   │
                            │ + Function URL   │
                            └──────────────────┘
```

- **`src/app.ts`** — The shared Hono application with all routes, middleware, and configuration. Used by both local dev and Lambda.
- **`src/index.ts`** — Node entry point for local development (`pnpm run dev`), served via `@hono/node-server`.
- **`lambda/index.ts`** — Lambda entry point. Wraps the shared app with `hono/aws-lambda`'s `handle()` function.
- **`infra/stack.ts`** — AWS CDK stack that defines the Lambda function, its configuration, and the Function URL.

---

## Prerequisites

| Requirement         | Version | Check                                                                |
| ------------------- | ------- | -------------------------------------------------------------------- |
| **Node.js**         | 18+     | `node --version`                                                     |
| **pnpm**            | 8+      | `pnpm --version`                                                     |
| **AWS CLI**         | 2.x     | `aws --version`                                                      |
| **AWS Account**     | —       | [Sign up](https://aws.amazon.com/)                                   |
| **IAM Permissions** | —       | Needs permissions to create Lambda, IAM roles, CloudFormation stacks |

---

## Project Structure

```
apps/server/
├── cdk.json                  ← CDK configuration (uses tsx to run stack)
├── infra/
│   └── stack.ts              ← CDK stack definition (Lambda + Function URL)
├── lambda/
│   └── index.ts              ← Lambda handler entry point
├── src/
│   ├── app.ts                ← Shared Hono app (routes, middleware)
│   ├── index.ts              ← Node/local entry point (unchanged)
│   └── ...
├── .env                      ← Local development env vars
├── .env.production           ← Production env vars (you create this)
└── package.json              ← Scripts: cdk:deploy, cdk:synth, etc.
```

---

## How It Works

1. **CDK reads `infra/stack.ts`** — Defines a `NodejsFunction` Lambda using Node.js 22 runtime.
2. **esbuild bundles `lambda/index.ts`** — CDK uses esbuild under the hood to bundle your TypeScript code into a single minified JS file. It resolves all imports including `@/*` path aliases via your `tsconfig.json`.
3. **Environment variables** are loaded from `.env.production` at synth/deploy time and injected into the Lambda function configuration.
4. **A Function URL** is created — this gives you a public HTTPS endpoint directly backed by the Lambda function (no API Gateway needed, simpler and cheaper).
5. **CloudFormation deploys everything** — IAM role, Lambda function, Function URL, and all associated resources.

---

## Step-by-Step Deployment

### 1. Install AWS CLI

If you haven't already, install the AWS CLI:

- **Windows**: Download the [MSI installer](https://awscli.amazonaws.com/AWSCLIV2.msi)
- **macOS**: `brew install awscli`
- **Linux**: `curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && unzip awscliv2.zip && sudo ./aws/install`

Verify:

```bash
aws --version
# aws-cli/2.x.x ...
```

### 2. Configure AWS Credentials

You need an IAM user or role with sufficient permissions. Run:

```bash
aws configure
```

You'll be prompted for:

| Field                 | Example                     | Notes                        |
| --------------------- | --------------------------- | ---------------------------- |
| AWS Access Key ID     | `AKIAIOSFODNN7EXAMPLE`      | From IAM console             |
| AWS Secret Access Key | `wJalrXUtnFEMI/K7MDENG/...` | From IAM console             |
| Default region        | `us-east-1`                 | Choose your preferred region |
| Output format         | `json`                      | Leave as default             |

> **Tip**: You can also set the region for CDK specifically via the `CDK_DEFAULT_REGION` environment variable. The stack defaults to `us-east-1` if not set.

### 3. Create Production Environment File

Create a `.env.production` file in `apps/server/` with your production values:

```bash
# From apps/server/
cp .env.example .env.production
```

Then edit `.env.production` with your actual production values:

```env
NODE_ENV="production"
FRONTEND_URL="https://your-frontend-domain.com"
LOG_LEVEL="info"
DATABASE_URL="postgresql://user:password@your-db-host:5432/repo"
DIRECT_URL="postgresql://user:password@your-db-host:5432/repo"
```

> **Important**: Make sure your database is accessible from Lambda. If using a managed database (e.g., AWS RDS, Supabase, Neon), ensure the connection string is correct and the database allows connections from AWS Lambda's IP range. Serverless databases like **Neon** or **Supabase** work out of the box.

### 4. Bootstrap CDK (First Time Only)

CDK needs to set up some initial resources in your AWS account (an S3 bucket for assets and an IAM role). This is a **one-time** setup per AWS account per region:

```bash
# From apps/server/
npx cdk bootstrap
```

You should see output like:

```
 ⏳  Bootstrapping environment aws://123456789012/us-east-1...
 ✅  Environment aws://123456789012/us-east-1 bootstrapped
```

### 5. Preview Changes (Optional)

Before deploying, you can preview what CDK will create/change:

```bash
# Synthesize the CloudFormation template (dry run)
pnpm run cdk:synth

# Compare with current deployed state
pnpm run cdk:diff
```

`cdk synth` generates the CloudFormation template in `cdk.out/` so you can inspect it. `cdk diff` shows you what will change compared to what's already deployed.

### 6. Deploy

```bash
# From apps/server/
pnpm run cdk:deploy
```

Or from the monorepo root:

```bash
turbo run cdk:deploy --filter=@repo/api
```

CDK will:

1. Bundle `lambda/index.ts` and all its dependencies using esbuild
2. Create/update the CloudFormation stack `repoServerStack`
3. Provision the Lambda function, IAM role, and Function URL
4. Output the Function URL

You'll see output like:

```
 ✅  repoServerStack

 ✨  Deployment time: 45.2s

Outputs:
repoServerStack.FunctionUrl = https://abc123xyz.lambda-url.us-east-1.on.aws/
repoServerStack.FunctionName = repoServerStack-repoServerFunction-AbCdEf

Stack ARN:
arn:aws:cloudformation:us-east-1:123456789012:stack/repoServerStack/...
```

**The `FunctionUrl` is your production API endpoint.** Test it:

```bash
curl https://abc123xyz.lambda-url.us-east-1.on.aws/api/v1/demo
```

---

## CDK Commands Reference

All commands are run from `apps/server/`:

| Command                | Description                                        |
| ---------------------- | -------------------------------------------------- |
| `pnpm run cdk:synth`   | Generate CloudFormation template without deploying |
| `pnpm run cdk:diff`    | Preview what will change in the next deploy        |
| `pnpm run cdk:deploy`  | Deploy (or update) to AWS Lambda                   |
| `pnpm run cdk:destroy` | Delete the entire stack from AWS                   |

---

## Updating the Deployment

After making code changes to your Hono routes, middleware, or any `src/` files, simply re-deploy:

```bash
pnpm run cdk:deploy
```

CDK will detect the code change, re-bundle with esbuild, and update only the Lambda function code. Infrastructure changes (memory, timeout, env vars, etc.) are also handled automatically.

---

## Environment Variables

Environment variables are injected into the Lambda at deploy time. They are loaded from `.env.production` by the CDK stack (`infra/stack.ts`).

| Variable       | Description                                           | Required |
| -------------- | ----------------------------------------------------- | -------- |
| `NODE_ENV`     | Always set to `"production"` by CDK                   | Auto     |
| `PORT`         | Injected by CDK; ignored by Lambda (passthrough)      | Auto     |
| `FRONTEND_URL` | Your frontend's URL (for CORS)                        | ✅       |
| `LOG_LEVEL`    | Pino log level (defaults to `"info"`)                 | Optional |
| `DATABASE_URL` | PostgreSQL connection string (pooled)                 | ✅       |
| `DIRECT_URL`   | PostgreSQL connection string (direct, for migrations) | ✅       |

These are the variables validated by `src/env.ts` and injected by `infra/stack.ts`. If you add a new variable to the env schema, remember to add it to the `environment` block in `infra/stack.ts` as well — otherwise it won't reach the Lambda.

**To update an environment variable after deployment:**

1. Edit `.env.production`
2. Run `pnpm run cdk:deploy`

> **Note**: `PORT` is unused at runtime in Lambda — Lambda manages the HTTP listener internally — but the stack still injects it so that `env.ts`'s Zod schema validation passes. The `dotenv` call in `env.ts` will silently no-op in Lambda since there's no `.env` file present; env vars come from the Lambda runtime config instead.

---

## Customizing the Lambda

You can adjust the Lambda configuration in `infra/stack.ts`:

### Memory

```typescript
memorySize: 512, // default: 256 MB
```

More memory also means more CPU. For CPU-intensive or latency-sensitive workloads, consider 512MB or higher.

### Timeout

```typescript
timeout: cdk.Duration.seconds(60), // default: 30s
```

Lambda max timeout is 15 minutes (900 seconds).

### Region

Set the `CDK_DEFAULT_REGION` environment variable, or edit the stack:

```typescript
new repoServerStack(app, "repoServerStack", {
  env: {
    region: "ap-south-1" // Mumbai
  }
});
```

### Adding API Gateway (Instead of Function URL)

If you need features like custom domains, API keys, usage plans, or WAF integration, replace the Function URL with API Gateway:

```typescript
import * as apigw from "aws-cdk-lib/aws-apigatewayv2";
import { HttpLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";

const integration = new HttpLambdaIntegration("LambdaIntegration", fn);

const api = new apigw.HttpApi(this, "RepoApi", {
  defaultIntegration: integration
});

new cdk.CfnOutput(this, "ApiUrl", { value: api.url! });
```

### Enabling Response Streaming

For streaming responses (e.g., chat), update `lambda/index.ts`:

```typescript
import { streamHandle } from "hono/aws-lambda";
export const handler = streamHandle(app);
```

And in `infra/stack.ts`, enable stream mode on the Function URL:

```typescript
const fnUrl = fn.addFunctionUrl({
  authType: lambda.FunctionUrlAuthType.NONE,
  invokeMode: lambda.InvokeMode.RESPONSE_STREAM
});
```

---

## Tearing Down

To completely remove the Lambda function and all associated resources:

```bash
pnpm run cdk:destroy
```

You'll be asked to confirm. Type `y` to proceed. This deletes:

- The Lambda function
- The IAM role
- The Function URL
- The CloudFormation stack

> **Note**: This does NOT delete your database, CDK bootstrap resources, or `.env.production` file.

---

## Troubleshooting

### "Unable to resolve AWS account" during deploy

Make sure your AWS credentials are configured:

```bash
aws sts get-caller-identity
```

If this fails, re-run `aws configure`.

### "CDKToolkit stack not found" during deploy

You need to bootstrap CDK first:

```bash
npx cdk bootstrap
```

### Lambda timeout / memory errors

Increase the values in `infra/stack.ts`:

```typescript
memorySize: 512,
timeout: cdk.Duration.seconds(60),
```

Then re-deploy with `pnpm run cdk:deploy`.

### Database connection issues from Lambda

- Ensure your database allows connections from AWS IP ranges
- If using RDS in a VPC, you'll need to configure VPC settings in the CDK stack
- Serverless databases (Neon, Supabase, PlanetScale) work without VPC configuration

### "cdk synth" fails with module errors

Make sure all dependencies are installed:

```bash
cd apps/server
pnpm install
```

---

## Local Development (Unchanged)

The Lambda deployment does **not** affect local development. Your existing workflow remains the same:

```bash
# Start dev server with hot reload
pnpm run dev

# Run tests
pnpm run test

# Compile TypeScript to dist/ (for local/VM deployment via `pnpm run start`)
pnpm run build
```

The key insight is that `src/app.ts` is the shared application used by both entry points:

- **Local**: `src/index.ts` → imports `app.ts` → serves via `@hono/node-server`
- **Lambda**: `lambda/index.ts` → imports `app.ts` → wraps with `hono/aws-lambda` handler
