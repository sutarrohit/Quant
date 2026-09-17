import { Prisma } from '@quant/prisma';
import type { PrismaClient, Wallet } from '@quant/prisma';
import type { PrivyClient } from '@privy-io/node';

import { walletsFromLinkedAccounts, type PrivyWallet } from '../lib/privy-wallets.js';

export interface WalletSyncResult {
  wallets: Wallet[];
  // Addresses Privy reports for this user that are already recorded against a
  // different one. Surfaced rather than swallowed -- see `sync` below.
  conflicts: string[];
}

/**
 * Keeps the `wallet` table in step with Privy's `linked_accounts`.
 *
 * Privy is the only source: the browser knows the user's address, but a browser can
 * claim any address, and an address is exactly the kind of value that must not be
 * taken on the client's word. The client's role is to say *when* to look (it sees
 * the wallet appear), never *what* was found.
 */
export class WalletService {
  constructor(
    private readonly prisma: PrismaClient,
    private readonly privy: PrivyClient
  ) {}

  // Wallets already recorded for the user, embedded first so a caller that wants
  // "the" wallet can take the head of the list.
  async list(userId: string): Promise<Wallet[]> {
    return this.prisma.wallet.findMany({
      where: { userId },
      orderBy: [{ walletClient: 'asc' }, { createdAt: 'asc' }],
    });
  }

  // Re-reads the user's linked accounts from Privy and writes what they hold.
  // The extra API call is why this is not on the hot path: requireAuth syncs from
  // the payload it already has, and this runs only when a client reports a wallet
  // the database has not caught up with.
  async syncFromPrivy(userId: string, privyDid: string): Promise<WalletSyncResult> {
    const privyUser = await this.privy.users()._get(privyDid);
    return this.sync(userId, walletsFromLinkedAccounts(privyUser.linked_accounts));
  }

  /**
   * Upsert the given wallets for the user, then return every wallet they own.
   *
   * Idempotent by (chainType, address): a repeat sync refreshes the mutable fields
   * and creates nothing. Re-running it is the normal case, not an edge case.
   *
   * A row that already belongs to a *different* user is left untouched and reported
   * as a conflict. Reassigning it would let a second account quietly take over an
   * external wallet the first one linked, and an embedded wallet can never reach
   * this branch -- Privy mints it per user.
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
          // `userId` is deliberately absent: the branch above already established
          // that any existing row is this user's, and leaving it out means a race
          // cannot move a wallet between users.
          update: {
            walletClient: wallet.walletClient,
            privyWalletId: wallet.privyWalletId,
            firstVerifiedAt: wallet.firstVerifiedAt,
          },
        });
      } catch (err) {
        // Concurrent first syncs race between the read above and this write, and
        // one loses on the unique index (P2002). The winner wrote the same values,
        // so the loser has nothing left to do. Anything else is a real failure and
        // is not this method's to swallow.
        const lostRace = err instanceof Prisma.PrismaClientKnownRequestError && err.code === 'P2002';
        if (!lostRace) throw err;
      }
    }

    return { wallets: await this.list(userId), conflicts };
  }
}
