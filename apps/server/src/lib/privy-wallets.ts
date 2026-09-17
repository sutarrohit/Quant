import type { LinkedAccount } from '@privy-io/node/resources';

// Privy's access token carries only the DID, so wallets -- like the profile fields
// in privy-profile.ts -- live on the user's linked accounts and have to be fetched.
//
// Privy models a wallet as one of several linked-account variants: external
// Ethereum and Solana, plus one per embedded chain (ethereum, solana,
// bitcoin-segwit, bitcoin-taproot, curve-signing). Every one of them carries
// `type: 'wallet'`, `address`, `chain_type` and `wallet_client`, so narrowing on
// `type` alone reads them all -- and keeps working for a chain Privy adds later,
// which enumerating the variants would not. Verified against @privy-io/node's
// published types.
//
// `smart_wallet` is deliberately not a wallet here: it carries `type:
// 'smart_wallet'`, and a contract account is not a key the user signs with.

export interface PrivyWallet {
  address: string;
  chainType: string;
  walletClient: string;
  privyWalletId: string | null;
  firstVerifiedAt: Date | null;
}

// Privy's users resource documents its timestamps in seconds (`created_at` says so;
// the wallet fields carry no comment of their own but arrive in the same payload),
// while other resources in the same SDK use milliseconds. Rather than trust one
// reading, anything past 1e12 can only be milliseconds -- 1e12 *seconds* is the year
// 33658. Getting this wrong silently stores 1970 or an overflow Postgres rejects.
function toDate(value: number | null): Date | null {
  if (value === null) return null;

  const date = new Date(value > 1e12 ? value : value * 1000);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * Every wallet Privy has linked to the user, in the shape the `wallet` table keeps.
 *
 * An empty array is a normal result, not an error: the embedded wallet is created in
 * the browser at login, so a user's very first authenticated request can legitimately
 * arrive before Privy knows about any wallet at all.
 */
export function walletsFromLinkedAccounts(accounts: readonly LinkedAccount[]): PrivyWallet[] {
  const wallets: PrivyWallet[] = [];

  for (const account of accounts) {
    if (account.type !== 'wallet') continue;

    wallets.push({
      address: account.address,
      chainType: account.chain_type,
      // 'privy' on every embedded variant, 'unknown' on the external ones.
      walletClient: account.wallet_client,
      // Embedded wallets alone carry Privy's own wallet id -- the handle its
      // server-side wallet API takes. `in` keeps the read honest across the union.
      privyWalletId: ('id' in account ? account.id : null) ?? null,
      firstVerifiedAt: toDate(account.first_verified_at),
    });
  }

  return wallets;
}
