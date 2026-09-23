import { createHash } from 'node:crypto';

/**
 * Canonical JSON: object keys sorted at every depth, no incidental whitespace.
 *
 * Two specs that differ only in key order are the same strategy, and must hash
 * the same or the version history lies about what changed.
 */
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value === null || typeof value !== 'object') return value;

  const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) =>
    a < b ? -1 : a > b ? 1 : 0
  );
  return Object.fromEntries(entries.map(([k, v]) => [k, canonical(v)]));
}

/** The identity of a spec. Ours, not the engine's -- it computes its own. */
export function specHash(spec: unknown): string {
  return createHash('sha256').update(JSON.stringify(canonical(spec))).digest('hex');
}
