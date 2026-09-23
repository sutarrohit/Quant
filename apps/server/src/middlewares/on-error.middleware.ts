import type { ErrorHandler } from 'hono';
import type { ContentfulStatusCode } from 'hono/utils/http-status';
import * as HttpStatusCodes from 'stoker/http-status-codes';

import env from '../env.js';
import { ApiError } from '../lib/api-error.js';

// Every error needs a code -- clients branch on `code`, never on message text.
// Inverted from stoker's NAME -> number map, so all 58 statuses are covered.
const CODE_BY_STATUS: Record<number, string> = Object.fromEntries(
  Object.entries(HttpStatusCodes)
    .filter(([, status]) => typeof status === 'number')
    .map(([name, status]) => [status, name])
);

const onError: ErrorHandler = (err, c) => {
  const currentStatus = 'status' in err ? err.status : c.newResponse(null).status;
  const statusCode =
    currentStatus !== HttpStatusCodes.OK
      ? (currentStatus as ContentfulStatusCode)
      : HttpStatusCodes.INTERNAL_SERVER_ERROR;

  const code = err instanceof ApiError ? err.code : (CODE_BY_STATUS[statusCode] ?? 'INTERNAL_SERVER_ERROR');
  const details = err instanceof ApiError ? err.details : undefined; // The engine's spec errors.

  return c.json(
    {
      statusCode,
      code,
      message: err.message,
      ...(details === undefined ? {} : { details }),
      requestId: c.get('requestId'), // Quote this to trace the call through Hono and the engine.
      stack: env.NODE_ENV === 'production' ? undefined : err.stack,
    },
    statusCode
  );
};

export default onError;
