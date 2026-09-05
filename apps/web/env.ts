import { z } from 'zod';

const EnvSchema = z.object({
  NODE_ENV: z.string().default('development'),
  NEXT_PUBLIC_API_URL: z.string().default('http://localhost:4000'),
});

export type Env = z.infer<typeof EnvSchema>;

const parsedEnv = EnvSchema.safeParse({
  NODE_ENV: process.env.NODE_ENV,
  NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
});

if (!parsedEnv.success) {
  console.error('Invalid frontend env | Missing env:');
  console.error(JSON.stringify(z.flattenError(parsedEnv.error).fieldErrors, null, 2));
  throw new Error('Invalid frontend env');
}

export default parsedEnv.data;
