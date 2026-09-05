import { z } from '@hono/zod-openapi';

// Shape returned by the global onError handler for an ApiError throw.
export const ApiErrorSchema = z.object({
  statusCode: z.number(),
  code: z.string(),
  message: z.string(),
});
