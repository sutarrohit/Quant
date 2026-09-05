import { testClient } from 'hono/testing';

import app from '../../src/app.js';

export const client = testClient(app);
export default client;
