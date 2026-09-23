import { z } from 'zod';

/** The shape onError returns for every failure. Clients branch on `code`. */
export const ApiErrorSchema = z.object({
  statusCode: z.number(),
  code: z.string(),
  message: z.string(),
  details: z.unknown().optional(), // A 422 from the engine puts its per-field spec errors here.
  requestId: z.string().optional(), // Also the x-request-id header; traces the call into the engine.
});

export type ApiErrorBody = z.infer<typeof ApiErrorSchema>;
