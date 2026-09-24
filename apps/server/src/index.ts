import { serve } from '@hono/node-server';
import app from './app.js';
import { simulationService } from './lib/container.js';
import { startFillSync } from './lib/fill-sync.js';

serve(
  {
    fetch: app.fetch,
    port: 4000,
  },
  (info) => {
    console.log(
      `Server is running on http://localhost:${info.port} \n  Documentation on http://localhost:${info.port}/docs`
    );
  }
);

startFillSync(simulationService);
