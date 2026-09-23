import { z } from 'zod';

// Client-safe only: this module is imported by client components. The API's
// address is server-only (`API_URL` in next.config.ts).
const EnvSchema = z.object({
  NODE_ENV: z.string().default('development'),

  // Public by design. Must name the same app as the server's PRIVY_APP_ID, or
  // tokens fail their audience check. Production needs its own, bound to a domain.
  NEXT_PUBLIC_PRIVY_APP_ID: z.string().min(1),
  NEXT_PUBLIC_PRIVY_CLIENT_ID: z.string().optional(), // Only some dashboards issue one.
});

export type Env = z.infer<typeof EnvSchema>;

// Next inlines `process.env.NEXT_PUBLIC_*` only at literal reference sites, so
// each must be named rather than spread.
const parsedEnv = EnvSchema.safeParse({
  NODE_ENV: process.env.NODE_ENV,
  NEXT_PUBLIC_PRIVY_APP_ID: process.env.NEXT_PUBLIC_PRIVY_APP_ID,
  NEXT_PUBLIC_PRIVY_CLIENT_ID: process.env.NEXT_PUBLIC_PRIVY_CLIENT_ID,
});

if (!parsedEnv.success) {
  console.error('Invalid frontend env | Missing env:');
  console.error(JSON.stringify(z.flattenError(parsedEnv.error).fieldErrors, null, 2));
  throw new Error('Invalid frontend env');
}

export default parsedEnv.data;
