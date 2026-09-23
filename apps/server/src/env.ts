import { config } from 'dotenv';
import { expand } from 'dotenv-expand';
import path from 'node:path';
import { z } from 'zod';

// One file per NODE_ENV; `.env` is the default.
const ENV_FILES: Record<string, string> = {
  test: '.env.test',
  production: '.env.production',
};

expand(
  config({
    path: path.resolve(process.cwd(), ENV_FILES[process.env.NODE_ENV ?? ''] ?? '.env'),
  })
);

const EnvSchema = z.object({
  NODE_ENV: z.string().default('development'),
  PORT: z.coerce.number().default(4000),
  FRONTEND_URL: z.string().url().default('http://localhost:3000'),
  LOG_LEVEL: z.enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace', 'silent']),
  DATABASE_URL: z.url(),
  PUBLIC_URL: z.url(), // this API's own public base URL

  PRIVY_APP_ID: z.string().min(1), // Must match the web app's, or tokens fail their audience check.
  PRIVY_APP_SECRET: z.string().min(1),
  PRIVY_VERIFICATION_KEY: z.string().min(1), // Dashboard public key; verifies tokens locally.

  ENGINE_URL: z.string().url().default('http://localhost:8000'),
  ENGINE_INTERNAL_API_KEY: z.string().min(1), // Must equal the engine's NT_INTERNAL_API_KEY.
});

export type env = z.infer<typeof EnvSchema>;

const { data: env, error } = EnvSchema.safeParse(process.env);

if (error) {
  console.error('❌ Invalid env | Missing env:');
  console.error(JSON.stringify(z.flattenError(error).fieldErrors, null, 2));
  process.exit(1);
}

export default env!;
