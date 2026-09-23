import { engineFetch } from '../lib/engine-client.js';
import type { Catalog } from '../types/catalog.js';

const TTL_MS = 60_000; // A latency cache, not a source of truth, so in-process is fine.

let cached: { at: number; value: Catalog } | null = null;

export async function getCatalog(requestId?: string): Promise<Catalog> {
  if (cached && Date.now() - cached.at < TTL_MS) return cached.value;

  const value = await engineFetch<Catalog>('/v1/catalog/instruments', { requestId });
  cached = { at: Date.now(), value };
  return value;
}

/** Drops the cache. For tests, and for whatever ingests data later. */
export function clearCatalogCache(): void {
  cached = null;
}
