import type { LinkedAccount } from '@privy-io/node/resources';

// Wallets live on the user's linked accounts, since the token carries only the DID.
// Every wallet variant carries `type: 'wallet'`, so narrowing on `type` alone reads
// them all -- including a chain Privy adds later. `smart_wallet` is excluded: a
// contract account is not a key the user signs with.

export interface PrivyWallet {
  address: string;
  chainType: string;
  walletClient: string;
  privyWalletId: string | null;
  firstVerifiedAt: Date | null;
}

// Privy's SDK mixes seconds and milliseconds across resources. Anything past 1e12
// can only be ms -- 1e12 seconds is the year 33658. Guessing stores 1970 or overflows.
function toDate(value: number | null): Date | null {
  if (value === null) return null;

  const date = new Date(value > 1e12 ? value : value * 1000);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * Every wallet Privy has linked to the user, shaped for the `wallet` table.
 * Empty is normal: the first request can arrive before Privy knows about any wallet.
 */
export function walletsFromLinkedAccounts(accounts: readonly LinkedAccount[]): PrivyWallet[] {
  const wallets: PrivyWallet[] = [];

  for (const account of accounts) {
    if (account.type !== 'wallet') continue;

    wallets.push({
      address: account.address,
      chainType: account.chain_type,
      walletClient: account.wallet_client, // 'privy' when embedded, 'unknown' when external.
      privyWalletId: ('id' in account ? account.id : null) ?? null, // Embedded wallets only.
      firstVerifiedAt: toDate(account.first_verified_at),
    });
  }

  return wallets;
}
