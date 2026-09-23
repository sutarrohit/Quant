import { createRoute } from '@hono/zod-openapi';
import * as HttpStatusCodes from 'stoker/http-status-codes';
import jsonContent from 'stoker/openapi/helpers/json-content';

import { CatalogSchema } from '../../types/catalog.js';
import { ApiErrorSchema } from '@quant/contracts/error';

// GET route -- what can actually be backtested. Every instrument and bar-type
// picker is built from this, so a user composes a request that will validate.
export const getCatalogRoute = createRoute({
  method: 'get',
  path: '/instruments',
  tags: ['Catalog'],
  responses: {
    [HttpStatusCodes.OK]: jsonContent(CatalogSchema, 'Instruments and the bar types held for each'),
    [HttpStatusCodes.UNAUTHORIZED]: jsonContent(ApiErrorSchema, 'Not authenticated'),
    [HttpStatusCodes.BAD_GATEWAY]: jsonContent(ApiErrorSchema, 'The engine could not be reached'),
  },
});
