import type { LinkedAccount } from '@privy-io/node/resources';
import { describe, expect, it } from 'vitest';

import { walletsFromLinkedAccounts } from '../../src/lib/privy-wallets.js';

// Fixtures are cut down from @privy-io/node's published account types -- only the
// fields the extractor reads are kept, so a shape change in one of them shows up
// here as a type error rather than a silent null.
const embeddedEthereum = {
  id: 'wallet-id-1',
  address: '0xAbC0000000000000000000000000000000000001',
  chain_type: 'ethereum',
  connector_type: 'embedded',
  first_verified_at: 1_764_000_000,
  type: 'wallet',
  wallet_client: 'privy',
  wallet_client_type: 'privy',
} as unknown as LinkedAccount;

const externalEthereum = {
  address: '0xDeF0000000000000000000000000000000000002',
  chain_type: 'ethereum',
  first_verified_at: null,
  type: 'wallet',
  wallet_client: 'unknown',
} as unknown as LinkedAccount;

const email = {
  address: 'trader@example.com',
  type: 'email',
  first_verified_at: 1_764_000_000,
} as unknown as LinkedAccount;

const smartWallet = {
  address: '0x5A70000000000000000000000000000000000003',
  type: 'smart_wallet',
  smart_wallet_type: 'safe',
} as unknown as LinkedAccount;

describe('walletsFromLinkedAccounts', () => {
  it('reads the embedded wallet, including the Privy wallet id', () => {
    expect(walletsFromLinkedAccounts([embeddedEthereum])).toEqual([
      {
        address: '0xAbC0000000000000000000000000000000000001',
        chainType: 'ethereum',
        walletClient: 'privy',
        privyWalletId: 'wallet-id-1',
        firstVerifiedAt: new Date(1_764_000_000 * 1000),
      },
    ]);
  });

  it('reads an external wallet, which carries no Privy wallet id', () => {
    const [wallet] = walletsFromLinkedAccounts([externalEthereum]);

    expect(wallet?.walletClient).toBe('unknown');
    expect(wallet?.privyWalletId).toBeNull();
    expect(wallet?.firstVerifiedAt).toBeNull();
  });

  it('ignores accounts that are not wallets', () => {
    // A smart wallet is a contract account, not a key -- and `email` accounts also
    // carry an `address`, which is the trap this guards.
    expect(walletsFromLinkedAccounts([email, smartWallet])).toEqual([]);
  });

  it('keeps every wallet when a user has more than one', () => {
    const wallets = walletsFromLinkedAccounts([embeddedEthereum, email, externalEthereum]);

    expect(wallets.map((wallet) => wallet.address)).toEqual([
      '0xAbC0000000000000000000000000000000000001',
      '0xDeF0000000000000000000000000000000000002',
    ]);
  });

  it('reads a millisecond timestamp as milliseconds', () => {
    // Privy's users resource documents seconds, but other resources in the same SDK
    // send milliseconds. Either lands on the same instant instead of the year 33658.
    const ms = { ...(embeddedEthereum as object), first_verified_at: 1_764_000_000_000 } as unknown as LinkedAccount;

    expect(walletsFromLinkedAccounts([ms])[0]?.firstVerifiedAt).toEqual(new Date(1_764_000_000_000));
  });

  it('returns nothing when the wallet has not been created yet', () => {
    // The normal state of a first authenticated request: the embedded wallet is
    // created in the browser, and the API call can beat it.
    expect(walletsFromLinkedAccounts([])).toEqual([]);
  });
});
