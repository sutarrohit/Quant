import { hc } from 'hono/client';
import type { AppType } from '../app.js';

const client = hc<AppType>('http://localhost:4000');
