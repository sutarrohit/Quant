import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '../../src/lib/api-error.js';
import { camelize, engineFetch } from '../../src/lib/engine-client.js';

// A stand-in for the engine: each test says what it answers.
function respondWith(status: number, body: unknown, init?: { invalidJson?: boolean }) {
  const fetchMock = vi.fn(async () =>
    init?.invalidJson
      ? new Response('<html>502 Bad Gateway</html>', { status })
      : new Response(JSON.stringify(body), {
          status,
          headers: { 'Content-Type': 'application/json' },
        })
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('camelize', () => {
  it('rewrites snake_case keys at every depth', () => {
    expect(camelize({ account_id: 'a', desired: { spec_hash: 'h', bar_type: 'b' } })).toEqual({
      accountId: 'a',
      desired: { specHash: 'h', barType: 'b' },
    });
  });

  it('leaves keys that are already camelCase alone', () => {
    // A response can carry both at once: live state is snake_case, but the
    // summary nested inside it is camelCase at the source.
    expect(camelize({ observed: { status: 'RUNNING' }, summary: { totalReturn: '1.2' } })).toEqual({
      observed: { status: 'RUNNING' },
      summary: { totalReturn: '1.2' },
    });
  });

  it('rewrites keys inside arrays', () => {
    expect(camelize({ bar_types: [{ bar_type: 'x', start: null }] })).toEqual({
      barTypes: [{ barType: 'x', start: null }],
    });
  });

  it('never touches values', () => {
    // Money is a decimal string end to end.
    expect(camelize({ total_return: '-7.331184', instrument_id: 'SOLUSDT.BINANCE' })).toEqual({
      totalReturn: '-7.331184',
      instrumentId: 'SOLUSDT.BINANCE',
    });
  });
});

describe('engineFetch', () => {
  it('sends the bearer token and returns the body camelized', async () => {
    const fetchMock = respondWith(200, { instruments: [{ instrument_id: 'SOLUSDT.BINANCE' }] });

    const body = await engineFetch<{ instruments: { instrumentId: string }[] }>(
      '/v1/catalog/instruments'
    );

    expect(body.instruments[0]?.instrumentId).toBe('SOLUSDT.BINANCE');
    const headers = (fetchMock.mock.calls[0]?.[1] as RequestInit).headers as Record<string, string>;
    expect(headers.Authorization).toMatch(/^Bearer .+/);
  });

  it('forwards a request id so one id traces both services', async () => {
    const fetchMock = respondWith(200, {});

    await engineFetch('/v1/catalog/instruments', { requestId: 'req_abc' });

    const headers = (fetchMock.mock.calls[0]?.[1] as RequestInit).headers as Record<string, string>;
    expect(headers['x-request-id']).toBe('req_abc');
  });

  it('appends query parameters and drops undefined ones', async () => {
    const fetchMock = respondWith(200, { rows: [], total: 0 });

    await engineFetch('/v1/backtests/job_1/artifacts/trades', {
      query: { offset: 10, limit: undefined },
    });

    const url = new URL(String(fetchMock.mock.calls[0]?.[0]));
    expect(url.searchParams.get('offset')).toBe('10');
    expect(url.searchParams.has('limit')).toBe(false);
  });

  it('keeps the engine error code so a client can branch on it', async () => {
    respondWith(404, { code: 'JOB_NOT_FOUND', message: 'no such job' });

    const error = await engineFetch('/v1/backtests/job_1').catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(404);
    expect((error as ApiError).code).toBe('JOB_NOT_FOUND');
  });

  it('carries a spec rejection through as a list, not a sentence', async () => {
    // The builder marks every bad field in one pass, so the list must survive.
    respondWith(422, {
      errors: [
        { path: 'exit', code: 'MISSING_STOP_LOSS', message: 'riskPercent sizing needs a stop' },
        { path: 'entry.all[0]', code: 'MISSING_THRESHOLD', message: 'no value or reference' },
      ],
    });

    const error = (await engineFetch('/v1/backtests', {
      method: 'POST',
      body: {},
    }).catch((e: unknown) => e)) as ApiError;

    expect(error.status).toBe(422);
    expect(error.code).toBe('SPEC_INVALID');
    expect(error.details).toHaveLength(2);
    expect((error.details as { code: string }[])[0]?.code).toBe('MISSING_STOP_LOSS');
  });

  it('never passes the engine’s 401 through to the caller', async () => {
    // The engine rejecting OUR token is our misconfiguration -- forwarding it
    // would bounce a signed-in user to the login page.
    respondWith(401, { code: 'UNAUTHENTICATED', message: 'a valid internal bearer token' });

    const error = (await engineFetch('/v1/catalog/instruments').catch((e: unknown) => e)) as ApiError;

    expect(error.status).toBe(502);
    expect(error.code).toBe('ENGINE_UNAUTHORIZED');
  });

  it('turns an unreachable engine into a 502, not a 500', async () => {
    // 502 says upstream and retryable; 500 sends someone to the wrong logs.
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('fetch failed');
      })
    );

    const error = (await engineFetch('/v1/catalog/instruments').catch((e: unknown) => e)) as ApiError;

    expect(error.status).toBe(502);
    expect(error.code).toBe('ENGINE_UNAVAILABLE');
  });

  it('refuses a body it cannot parse rather than returning half of one', async () => {
    respondWith(200, null, { invalidJson: true });

    const error = (await engineFetch('/v1/catalog/instruments').catch((e: unknown) => e)) as ApiError;

    expect(error.status).toBe(502);
    expect(error.code).toBe('ENGINE_RESPONSE_INVALID');
  });
});
