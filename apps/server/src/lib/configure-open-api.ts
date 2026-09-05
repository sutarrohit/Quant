import type { AppBinding, AppOpenAPI } from '../types/index.js';
import { swaggerUI } from '@hono/swagger-ui';
import packageJSON from '../../package.json' with { type: 'json' };
import { Context } from 'hono';

export function configureOpenAPI(app: AppOpenAPI) {
  app.doc('/doc', {
    openapi: '3.0.0',
    info: {
      version: packageJSON.version,
      title: 'Employee Management',
    },
  });

  app.get(
    '/docs',
    swaggerUI({
      url: '/doc',
    })
  );

  app.get('/health', (c: Context<AppBinding>) => {
    return c.json({
      status: 'ok',
    });
  });

  return app;
}
