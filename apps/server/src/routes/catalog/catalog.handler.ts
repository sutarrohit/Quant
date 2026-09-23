import * as HttpStatusCodes from 'stoker/http-status-codes';

import { getCatalog } from '../../services/catalog.service.js';
import type { AppRouteHandler } from '../../types/app.js';
import type { getCatalogRoute } from './catalog.route.js';

// Handler for GET /instruments. A pass-through: rewriting the engine's answer
// here would give the UI a second opinion that can be wrong.
export const getCatalogHandler: AppRouteHandler<typeof getCatalogRoute> = async (c) => {
  const catalog = await getCatalog(c.req.header('x-request-id')); // Traces across both services.
  return c.json(catalog, HttpStatusCodes.OK);
};
