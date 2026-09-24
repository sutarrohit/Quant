import { Prisma, type PrismaClient } from '@quant/prisma';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SimulationService, type SimWithVersion } from '../../src/services/simulation.service.js';

// Fills copied from the engine's stream into Postgres (simulation-state plan, phase 4).

const SIM = {
  id: '11111111-1111-4111-8111-111111111111',
  userId: 'user_1',
  accountId: 'sim_abc',
  fillsSyncedTo: null as string | null,
  version: { strategyId: 's', version: 1, strategy: { name: 'x' } },
} as unknown as SimWithVersion;

const fill = (id: string, tradeId: string, side = 'BUY') => ({
  id,
  kind: 'FILL',
  at: '2026-09-24T06:00:00.184754Z',
  side,
  quantity: '1.741',
  price: '114.87',
  commission: { amount: '0.29998301', currency: 'USDT' },
  tradeId,
  clientOrderId: 'O-1',
});

// Serves pages of the stream by `after`, like the engine's XRANGE.
function stream(pages: Record<string, { events: unknown[]; last: string | null }>) {
  const asked: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: URL | string) => {
      const after = new URL(String(input)).searchParams.get('after') ?? '';
      asked.push(after);
      const body = pages[after] ?? { events: [], last: after };
      return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
    })
  );
  return asked;
}

function db() {
  const rows: Prisma.AccountFillCreateManyInput[] = [];
  const cursors: string[] = [];
  const prisma = {
    simulation: {
      findFirst: vi.fn(async () => SIM),
      update: vi.fn(async ({ data }: { data: { fillsSyncedTo: string } }) => cursors.push(data.fillsSyncedTo)),
    },
    accountFill: {
      createMany: vi.fn(async ({ data }: { data: Prisma.AccountFillCreateManyInput[] }) => {
        const fresh = data.filter((d) => !rows.some((r) => r.tradeId === d.tradeId));
        rows.push(...fresh);
        return { count: fresh.length };
      }),
      findMany: vi.fn(async () =>
        rows.map((r) => ({
          ...r,
          quantity: new Prisma.Decimal(String(r.quantity)),
          price: new Prisma.Decimal(String(r.price)),
          commission: new Prisma.Decimal(String(r.commission)),
          filledAt: r.filledAt,
        }))
      ),
      count: vi.fn(async () => rows.length),
    },
  } as unknown as PrismaClient;
  return { prisma, rows, cursors };
}

beforeEach(() => vi.unstubAllGlobals());
afterEach(() => vi.unstubAllGlobals());

describe('syncFills', () => {
  it('copies fills only, and moves the cursor to the last event read', async () => {
    const { prisma, rows, cursors } = db();
    stream({
      '0-0': {
        events: [{ id: '1-0', kind: 'SIGNAL', at: 'x' }, fill('2-0', 'T-1'), { id: '3-0', kind: 'NODE_STOPPED', at: 'x' }],
        last: '3-0',
      },
    });

    const copied = await new SimulationService(prisma).syncFills(SIM, 1_000_000);

    expect(copied).toBe(1);
    expect(rows).toMatchObject([
      { accountId: 'sim_abc', tradeId: 'T-1', side: 'BUY', commission: '0.29998301', commissionCurrency: 'USDT' },
    ]);
    expect(cursors).toEqual(['3-0']);
  });

  it('starts from the row cursor, not from the beginning', async () => {
    const { prisma } = db();
    const asked = stream({});

    await new SimulationService(prisma).syncFills({ ...SIM, fillsSyncedTo: '7-0' } as SimWithVersion, 1_000_000);

    expect(asked).toEqual(['7-0']);
  });

  it('keeps reading while pages come back full', async () => {
    const { prisma, rows } = db();
    const full = Array.from({ length: 1_000 }, (_, i) => fill(`${i + 1}-0`, `T-${i}`));
    const asked = stream({
      '0-0': { events: full, last: '1000-0' },
      '1000-0': { events: [fill('1001-0', 'T-last', 'SELL')], last: '1001-0' },
    });

    await new SimulationService(prisma).syncFills(SIM, 1_000_000);

    expect(asked).toEqual(['0-0', '1000-0']);
    expect(rows).toHaveLength(1_001);
  });

  it('copying the same fill twice leaves one row', async () => {
    const { prisma, rows } = db();
    stream({ '0-0': { events: [fill('1-0', 'T-1')], last: '1-0' } });
    const service = new SimulationService(prisma);

    await service.syncFills(SIM, 1_000_000);
    await service.syncFills(SIM, 1_010_000); // Row cursor unchanged in this fake, so it re-reads.

    expect(rows).toHaveLength(1);
  });

  it('copies at most once per five seconds per account', async () => {
    const { prisma } = db();
    const asked = stream({});
    const service = new SimulationService(prisma);

    await service.syncFills(SIM, 1_000_000);
    await service.syncFills(SIM, 1_004_999);
    await service.syncFills(SIM, 1_005_000);

    expect(asked).toHaveLength(2);
  });
});

describe('fills', () => {
  it('serves what Postgres holds when the engine is down', async () => {
    const { prisma, rows } = db();
    rows.push({
      accountId: 'sim_abc',
      tradeId: 'T-9',
      clientOrderId: 'O-9',
      side: 'SELL',
      quantity: '1.74',
      price: '114.96',
      commission: '0.3000456',
      commissionCurrency: 'USDT',
      filledAt: new Date('2026-09-24T04:36:00Z'),
    });
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('fetch failed'))));

    const page = await new SimulationService(prisma).fills('user_1', SIM.id, 1, 20);

    expect(page.data).toEqual([
      {
        tradeId: 'T-9',
        side: 'SELL',
        quantity: '1.74',
        price: '114.96',
        commission: { amount: '0.3000456', currency: 'USDT' },
        filledAt: '2026-09-24T04:36:00.000Z',
      },
    ]);
    expect(page.pagination).toEqual({ page: 1, pageSize: 20, total: 1, totalPages: 1 });
  });
});
