import createApp from './lib/create-app.js';
import { configureOpenAPI } from './lib/configure-open-api.js';

import userRouter from './routes/user/user.index.js';

const app = createApp();
configureOpenAPI(app);

// Each router declares the base path it is mounted at. user.index.ts already
// documented itself as living at /api/v1/user, and apps/web calls that path --
// only this file disagreed, mounting at '/' so every request 404'd.
const routes = [{ basePath: '/api/v1/user', router: userRouter }] as const;

routes.forEach(({ basePath, router }) => {
  app.route(basePath, router);
});

export type AppType = (typeof routes)[number]['router'];
export default app;
