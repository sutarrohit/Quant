import type { NotFoundHandler } from 'hono';

import { NOT_FOUND } from 'stoker/http-status-codes';
import { NOT_FOUND as NOT_FOUND_MESSAGE } from 'stoker/http-status-phrases';

// Same shape as onError, so a client handles an unknown route like any other error.
const notFound: NotFoundHandler = (c) =>
  c.json(
    {
      statusCode: NOT_FOUND,
      code: 'NOT_FOUND',
      message: `${NOT_FOUND_MESSAGE} - ${c.req.path}`,
      requestId: c.get('requestId'),
    },
    NOT_FOUND
  );

export default notFound;
