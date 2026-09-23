import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '../../src/lib/api-error.js';
import { clearCatalogCache, getCatalog } from '../../src/services/catalog.service.js';

const CATALOG = {
  instruments: [{ instrument_id: 'SOLUSDT.BINANCE' }],
  bar_types: [
    { bar_type: 'SOLUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL', start: '2024-01-01', end: '2024-03-01' },
  ],
};

function respondWith(status: number, body: unknown) {
  const fetchMock = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

beforeEach(() => {
  clearCatalogCache();
  vi.unstubAllGlobals();
});

afterEach(() => {
  clearCatalogCache();
  vi.unstubAllGlobals();
});

describe('getCatalog', () => {
  it('returns the engine catalog with camelCase keys', async () => {
    respondWith(200, CATALOG);

    const catalog = await getCatalog();

    expect(catalog.instruments[0]?.instrumentId).toBe('SOLUSDT.BINANCE');
    expect(catalog.barTypes[0]?.barType).toBe('SOLUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL');
  });

  it('serves a second read from cache', async () => {
    // Every instrument picker reads this, and it rarely changes.
    const fetchMock = respondWith(200, CATALOG);

    await getCatalog();
    await getCatalog();

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('does not cache a failure', async () => {
    // A cached 502 would keep the picker empty for a minute after recovery.
    respondWith(502, { code: 'ENGINE_ERROR', message: 'nope' });
    await expect(getCatalog()).rejects.toBeInstanceOf(ApiError);

    respondWith(200, CATALOG);
    await expect(getCatalog()).resolves.toMatchObject({
      instruments: [{ instrumentId: 'SOLUSDT.BINANCE' }],
    });
  });
});
