import type { PrismaClient, Wallet } from '@quant/prisma';
import { beforeEach, describe, expect, it } from 'vitest';

import type { PrivyWallet } from '../../src/lib/privy-wallets.js';
import { WalletService } from '../../src/services/wallet.service.js';

// An in-memory stand-in for the three calls the service makes, enforcing the one
// invariant that matters: (chainType, address) is unique across all users. A mock
// that let two rows share a key would prove nothing about the conflict branch.
function fakePrisma(seed: Wallet[] = []) {
  const rows = [...seed];
  const keyOf = (chainType: string, address: string) => `${chainType}:${address}`;

  const wallet = {
    findUnique: async ({ where }: { where: { chainType_address: { chainType: string; address: string } } }) => {
      const { chainType, address } = where.chainType_address;
      return rows.find((row) => keyOf(row.chainType, row.address) === keyOf(chainType, address)) ?? null;
    },
    findMany: async ({ where }: { where: { userId: string } }) => rows.filter((row) => row.userId === where.userId),
    upsert: async ({
      where,
      create,
      update,
    }: {
      where: { chainType_address: { chainType: string; address: string } };
      create: PrivyWallet & { userId: string };
      update: Partial<Wallet>;
    }) => {
      const { chainType, address } = where.chainType_address;
      const existing = rows.find((row) => keyOf(row.chainType, row.address) === keyOf(chainType, address));

      if (existing) {
        Object.assign(existing, update);
        return existing;
      }

      const row = { id: `row-${rows.length + 1}`, createdAt: new Date(), updatedAt: new Date(), ...create } as Wallet;
      rows.push(row);
      return row;
    },
  };

  return { prisma: { wallet } as unknown as PrismaClient, rows };
}

const privyClientStub = {} as never;

const embedded: PrivyWallet = {
  address: '0xAbC0000000000000000000000000000000000001',
  chainType: 'ethereum',
  walletClient: 'privy',
  privyWalletId: 'wallet-id-1',
  firstVerifiedAt: new Date('2026-09-01T00:00:00.000Z'),
};

describe('WalletService.sync', () => {
  let service: WalletService;
  let store: ReturnType<typeof fakePrisma>;

  beforeEach(() => {
    store = fakePrisma();
    service = new WalletService(store.prisma, privyClientStub);
  });

  it('stores a wallet the user did not have', async () => {
    const result = await service.sync('user-1', [embedded]);

    expect(result.conflicts).toEqual([]);
    expect(result.wallets).toHaveLength(1);
    expect(result.wallets[0]).toMatchObject({
      userId: 'user-1',
      address: embedded.address,
      walletClient: 'privy',
      privyWalletId: 'wallet-id-1',
    });
  });

  it('is idempotent -- a second sync creates nothing', async () => {
    await service.sync('user-1', [embedded]);
    const result = await service.sync('user-1', [embedded]);

    expect(store.rows).toHaveLength(1);
    expect(result.wallets).toHaveLength(1);
  });

  it('refreshes the mutable fields on a wallet it already has', async () => {
    await service.sync('user-1', [{ ...embedded, privyWalletId: null, firstVerifiedAt: null }]);
    const result = await service.sync('user-1', [embedded]);

    expect(result.wallets[0]).toMatchObject({
      privyWalletId: 'wallet-id-1',
      firstVerifiedAt: embedded.firstVerifiedAt,
    });
  });

  it('never moves a wallet that belongs to another user', async () => {
    await service.sync('user-1', [embedded]);

    const result = await service.sync('user-2', [embedded]);

    expect(result.conflicts).toEqual([embedded.address]);
    expect(result.wallets).toEqual([]);
    expect(store.rows).toHaveLength(1);
    expect(store.rows[0]?.userId).toBe('user-1');
  });

  it('keeps the same address on two chains apart', async () => {
    // (chainType, address) is the key, not address alone: the same bytes can be a
    // legitimate address on more than one chain.
    const result = await service.sync('user-1', [embedded, { ...embedded, chainType: 'solana' }]);

    expect(result.wallets).toHaveLength(2);
    expect(result.conflicts).toEqual([]);
  });

  it('writes nothing when Privy reports no wallet yet', async () => {
    const result = await service.sync('user-1', []);

    expect(result.wallets).toEqual([]);
    expect(store.rows).toEqual([]);
  });
});
