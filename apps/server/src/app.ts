import createApp from './lib/create-app.js';
import { configureOpenAPI } from './lib/configure-open-api.js';

import catalogRouter from './routes/catalog/catalog.index.js';
import strategyRouter from './routes/strategies/strategy.index.js';
import userRouter from './routes/user/user.index.js';

const app = createApp();
configureOpenAPI(app);

// Each router declares the base path it is mounted at.
const routes = [
  { basePath: '/api/v1/user', router: userRouter },
  { basePath: '/api/v1/catalog', router: catalogRouter },
  { basePath: '/api/v1/strategies', router: strategyRouter },
] as const;

routes.forEach(({ basePath, router }) => {
  app.route(basePath, router);
});

export type AppType = (typeof routes)[number]['router'];
export default app;
