import { z } from 'zod';

// Client-safe only. Every key here must be NEXT_PUBLIC_-prefixed or available in
// the browser, because this module is imported by client components. The API's
// address is NOT here -- it is server-only (`API_URL` in next.config.ts), since
// the browser now talks to this app's own origin and never to the API directly.
const EnvSchema = z.object({
  NODE_ENV: z.string().default('development'),

  // Privy app ID. Public by design -- it ships in the client bundle. The App
  // *Secret* is server-only and must never appear in this file.
  //
  // This must be the same Privy app the server's PRIVY_APP_ID names, or tokens
  // fail their audience check. Production uses a different app ID than dev,
  // because a cookie-enabled production app only works on its verified domain.
  NEXT_PUBLIC_PRIVY_APP_ID: z.string().min(1),
  // Optional in the SDK; only some dashboard configurations issue one.
  NEXT_PUBLIC_PRIVY_CLIENT_ID: z.string().optional(),
});

export type Env = z.infer<typeof EnvSchema>;

// Next.js inlines `process.env.NEXT_PUBLIC_*` only at literal reference sites,
// so each one has to be named explicitly here rather than spread from process.env.
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
