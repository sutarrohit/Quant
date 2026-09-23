import { createRouter } from '../../lib/create-app.js';
import { requireAuth } from '../../middlewares/index.middleware.js';

import { getCatalogHandler } from './catalog.handler.js';
import { getCatalogRoute } from './catalog.route.js';

// Mounted at /api/v1/catalog.
const catalogRouter = createRouter();

// Authenticated even though the catalog is not secret: an open route here is an
// open route to the engine with our bearer token attached.
catalogRouter.use('*', requireAuth);

export default catalogRouter.openapi(getCatalogRoute, getCatalogHandler);
