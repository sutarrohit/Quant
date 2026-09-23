import { Prisma } from '@quant/prisma';
import type { PrismaClient, Wallet } from '@quant/prisma';
import type { PrivyClient } from '@privy-io/node';

import { walletsFromLinkedAccounts, type PrivyWallet } from '../lib/privy-wallets.js';

export interface WalletSyncResult {
  wallets: Wallet[];
  conflicts: string[]; // Addresses already recorded against a different user.
}

/**
 * Keeps the `wallet` table in step with Privy's `linked_accounts`.
 * Privy is the only source -- a browser can claim any address. The client says
 * *when* to look, never *what* was found.
 */
export class WalletService {
  constructor(
    private readonly prisma: PrismaClient,
    private readonly privy: PrivyClient
  ) {}

  // Embedded first, so a caller wanting "the" wallet can take the head.
  async list(userId: string): Promise<Wallet[]> {
    return this.prisma.wallet.findMany({
      where: { userId },
      orderBy: [{ walletClient: 'asc' }, { createdAt: 'asc' }],
    });
  }

  // Off the hot path: requireAuth syncs from the payload it already has, and this
  // runs only when a client reports a wallet the database has not caught up with.
  async syncFromPrivy(userId: string, privyDid: string): Promise<WalletSyncResult> {
    const privyUser = await this.privy.users()._get(privyDid);
    return this.sync(userId, walletsFromLinkedAccounts(privyUser.linked_accounts));
  }

  /**
   * Upsert the given wallets, then return every wallet the user owns.
   *
   * Idempotent by (chainType, address); re-running is the normal case. A row owned
   * by a different user is reported as a conflict, never reassigned -- that would
   * let a second account take over an external wallet the first one linked.
   */
  async sync(userId: string, wallets: readonly PrivyWallet[]): Promise<WalletSyncResult> {
    const conflicts: string[] = [];

    for (const wallet of wallets) {
      const where = {
        chainType_address: { chainType: wallet.chainType, address: wallet.address },
      };

      const existing = await this.prisma.wallet.findUnique({ where });

      if (existing && existing.userId !== userId) {
        conflicts.push(wallet.address);
        continue;
      }

      try {
        await this.prisma.wallet.upsert({
          where,
          create: { userId, ...wallet },
          // `userId` absent on purpose, so a race cannot move a wallet between users.
          update: {
            walletClient: wallet.walletClient,
            privyWalletId: wallet.privyWalletId,
            firstVerifiedAt: wallet.firstVerifiedAt,
          },
        });
      } catch (err) {
        // Concurrent syncs race between the read and this write; the loser (P2002)
        // has nothing left to do, since the winner wrote the same values.
        const lostRace = err instanceof Prisma.PrismaClientKnownRequestError && err.code === 'P2002';
        if (!lostRace) throw err;
      }
    }

    return { wallets: await this.list(userId), conflicts };
  }
}
