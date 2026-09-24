import pino from 'pino';

import type { SimulationService } from '../services/simulation.service.js';

const EVERY_MS = 60_000; // The engine keeps ~1,000 events; a minute is far inside that.
const log = pino({ level: process.env.LOG_LEVEL || 'info', name: 'fill-sync' });

/**
 * Copy every simulation's new fills into Postgres on a timer, not only while its
 * page is open. One run at a time; returns a stop function. Started from index.ts
 * only, so tests and scripts never run it.
 */
export function startFillSync(service: SimulationService, every = EVERY_MS): () => void {
  let running = false;
  const timer = setInterval(() => {
    if (running) return; // A slow engine must not stack runs up.
    running = true;
    service
      .syncAllFills()
      .then(({ copied, failed }) => {
        if (copied || failed) log.info({ copied, failed }, 'fills synced');
      })
      .catch((error: unknown) => log.warn({ err: error }, 'fill sync failed'))
      .finally(() => {
        running = false;
      });
  }, every);
  timer.unref(); // Never the reason the process stays up.
  return () => clearInterval(timer);
}
