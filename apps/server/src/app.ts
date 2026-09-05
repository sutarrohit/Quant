import createApp from './lib/create-app.js';
import { configureOpenAPI } from './lib/configure-open-api.js';

import userRouter from './routes/user/user.index.js';

const app = createApp();
configureOpenAPI(app);

const routes = [userRouter] as const;

routes.forEach((route) => {
  app.route('/', route);
});

export type AppType = (typeof routes)[number];
export default app;
