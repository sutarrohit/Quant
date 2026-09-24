import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { PrismaClient } from '@quant/prisma';

import { ApiError } from '../../src/lib/api-error.js';
import { SimulationService } from '../../src/services/simulation.service.js';

// What a running simulation is doing: snapshot, events, equity (docs/simulation-state-plan.md).

const SIM = {
  id: '11111111-1111-4111-8111-111111111111',
  userId: 'user_1',
  accountId: 'sim_abc',
  versionId: '22222222-2222-4222-8222-222222222222',
  version: { strategyId: '33333333-3333-4333-8333-333333333333', version: 2, strategy: { name: 'SOL RSI' } },
};

const SNAPSHOT = {
  accountId: 'sim_abc',
  mode: 'SIMULATION',
  at: '2026-09-24T06:00:00Z',
  equity: '10012.5',
  pnl: '12.5',
  returnPercent: '0.125',
  quoteCurrency: 'USDT',
  position: { side: 'LONG', quantity: '1.741', avgEntry: '114.87' },
  strategy: { phase: 'IN_POSITION' },
  stale: false,
};

// Answers by path, like the engine; records every URL asked for.
function engine(routes: Record<string, [number, unknown]>) {
  const urls: string[] = [];
  const fetchMock = vi.fn(async (input: URL | string) => {
    const url = new URL(String(input));
    urls.push(url.pathname + url.search);
    const [status, body] = routes[url.pathname] ?? [404, { code: 'NOT_FOUND', message: 'no route' }];
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  });
  vi.stubGlobal('fetch', fetchMock);
  return urls;
}

// Only the owner's row comes back; anyone else's id reads as absent.
const prisma = {
  simulation: {
    findFirst: vi.fn(async ({ where }: { where: { id: string; userId: string } }) =>
      where.id === SIM.id && where.userId === SIM.userId ? SIM : null
    ),
  },
} as unknown as PrismaClient;

const service = new SimulationService(prisma);

beforeEach(() => vi.unstubAllGlobals());
afterEach(() => vi.unstubAllGlobals());

describe('snapshot', () => {
  it("reads the row's account and keeps the account id server-side", async () => {
    const urls = engine({ '/v1/live/sim_abc/snapshot': [200, SNAPSHOT] });

    const snapshot = await service.snapshot('user_1', SIM.id);

    expect(urls).toEqual(['/v1/live/sim_abc/snapshot']);
    expect(snapshot).not.toHaveProperty('accountId');
    expect(snapshot.equity).toBe('10012.5');
  });

  it("is a 404 for someone else's simulation, and the engine is never asked", async () => {
    const urls = engine({ '/v1/live/sim_abc/snapshot': [200, SNAPSHOT] });

    await expect(service.snapshot('user_2', SIM.id)).rejects.toMatchObject({
      status: 404,
      code: 'SIMULATION_NOT_FOUND',
    });
    expect(urls).toEqual([]);
  });

  it('passes on "not published yet" so the page can say it is starting', async () => {
    engine({ '/v1/live/sim_abc/snapshot': [404, { code: 'SNAPSHOT_NOT_FOUND', message: 'not yet' }] });

    const error = await service.snapshot('user_1', SIM.id).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 404, code: 'SNAPSHOT_NOT_FOUND' });
  });
});

describe('events and equity', () => {
  it('forwards the cursor and the limit', async () => {
    const urls = engine({ '/v1/live/sim_abc/events': [200, { events: [], last: '1-0' }] });

    const page = await service.events('user_1', SIM.id, '1-0', 50);

    expect(urls).toEqual(['/v1/live/sim_abc/events?after=1-0&limit=50']);
    expect(page.last).toBe('1-0');
  });

  it('leaves the cursor off the first read', async () => {
    const urls = engine({ '/v1/live/sim_abc/equity': [200, { points: [], last: null }] });

    await service.equity('user_1', SIM.id, undefined);

    expect(urls).toEqual(['/v1/live/sim_abc/equity']);
  });

  it("does not read someone else's activity", async () => {
    const urls = engine({});

    await expect(service.events('user_2', SIM.id, undefined, 100)).rejects.toMatchObject({ status: 404 });
    await expect(service.equity('user_2', SIM.id, undefined)).rejects.toMatchObject({ status: 404 });
    expect(urls).toEqual([]);
  });
});

describe('performance on a simulation row', () => {
  const live = {
    '/v1/live/sim_abc': [
      200,
      {
        desired: { status: 'RUNNING', revision: 3, spec_hash: 'h', strategy_version_id: 'v', updated_at: 'x' },
        observed: null,
        lease_holder: null,
      },
    ],
    '/v1/live/sim_abc/kill': [200, { account_id: 'sim_abc', kill_switch: 'RELEASED' }],
  } satisfies Record<string, [number, unknown]>;

  it('summarises the snapshot', async () => {
    engine({ ...live, '/v1/live/sim_abc/snapshot': [200, SNAPSHOT] });

    const sim = await service.get('user_1', SIM.id);

    expect(sim.performance).toEqual({
      equity: '10012.5',
      pnl: '12.5',
      returnPercent: '0.125',
      quoteCurrency: 'USDT',
      position: { side: 'LONG', quantity: '1.741' },
      phase: 'IN_POSITION',
      at: '2026-09-24T06:00:00Z',
      stale: false,
    });
  });

  it('is null before the first publish, without failing the row', async () => {
    engine({ ...live, '/v1/live/sim_abc/snapshot': [404, { code: 'SNAPSHOT_NOT_FOUND', message: 'not yet' }] });

    const sim = await service.get('user_1', SIM.id);

    expect(sim.performance).toBeNull();
    expect(sim.live?.desired.status).toBe('RUNNING');
  });
});
