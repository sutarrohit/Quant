import { config } from 'dotenv';
import { expand } from 'dotenv-expand';
import path from 'node:path';
import { z } from 'zod';

expand(
  config({
    path: path.resolve(process.cwd(), process.env.NODE_ENV === 'test' ? '.env.test' : '.env'),
  })
);

const EnvSchema = z.object({
  NODE_ENV: z.string().default('development'),
  PORT: z.coerce.number().default(4000),
  FRONTEND_URL: z.string().url().default('http://localhost:3000'),
  LOG_LEVEL: z.enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace', 'silent']),
  DATABASE_URL: z.url(),
  DIRECT_URL: z.url(),
  PUBLIC_URL: z.url(), // public base URL used to register the webhook

  // Privy. APP_ID must name the same Privy app the frontend uses, or every
  // token fails its audience check. VERIFICATION_KEY is the app's public key
  // from the dashboard; it makes verification local instead of a network call.
  PRIVY_APP_ID: z.string().min(1),
  PRIVY_APP_SECRET: z.string().min(1),
  PRIVY_VERIFICATION_KEY: z.string().min(1),
});

export type env = z.infer<typeof EnvSchema>;

const { data: env, error } = EnvSchema.safeParse(process.env);

if (error) {
  console.error('❌ Invalid env | Missing env:');
  console.error(JSON.stringify(z.flattenError(error).fieldErrors, null, 2));
  process.exit(1);
}

export default env!;
