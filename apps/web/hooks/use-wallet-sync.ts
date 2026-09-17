'use client';
import { usePrivy, useWallets } from '@privy-io/react-auth';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

import { syncWalletsMutationOptions, walletsQueryOptions } from '@/lib/api/user/user-queries';

// Ethereum addresses are EIP-55 checksummed, and a connector may hand back a
// different casing than Privy's API stores -- so those compare case-insensitively.
// Everything else (Solana's base58, for one) is case-significant and compares
// exactly, because lowercasing it would fold two genuinely different addresses
// together.
const addressKey = (address: string) => (address.startsWith('0x') ? address.toLowerCase() : address);

/**
 * Persist the user's wallet once Privy has created it.
 *
 * The embedded wallet is created in the browser at first login, which is after the
 * server has already provisioned the user row -- so the server cannot simply store
 * it on the way past. The browser is what sees the wallet appear, and this is it
 * saying so. It never sends the address: the server re-reads that from Privy, which
 * is the only party that can be believed about it.
 *
 * Fires only when Privy reports a wallet the server has not returned, so the steady
 * state is zero requests. Each address is attempted once per mount, which stops a
 * sync that comes back without it (Privy still propagating, or the wallet belongs to
 * another account) from looping.
 */
export function useWalletSync() {
  const { authenticated } = usePrivy();
  const { wallets, ready } = useWallets();
  // `enabled` matters: this hook lives in the protected layout, which also renders
  // for a signed-out visitor who navigated in on the client. Without the gate that
  // visitor's first paint fires a request the API can only answer with a 401.
  const { data: stored } = useQuery({ ...walletsQueryOptions(), enabled: authenticated });
  const queryClient = useQueryClient();
  const attempted = useRef(new Set<string>());

  const { mutate } = useMutation({
    ...syncWalletsMutationOptions(),
    // The response is the authoritative list, so write it straight into the cache
    // rather than invalidating and asking for what we already hold.
    onSuccess: (data) => queryClient.setQueryData(walletsQueryOptions().queryKey, data),
  });

  useEffect(() => {
    if (!authenticated || !ready || !stored) return;

    const known = new Set(stored.wallets.map((wallet) => addressKey(wallet.address)));
    const missing = wallets
      .map((wallet) => addressKey(wallet.address))
      .filter((key) => !known.has(key) && !attempted.current.has(key));

    if (missing.length === 0) return;

    missing.forEach((key) => attempted.current.add(key));
    mutate();
  }, [authenticated, ready, wallets, stored, mutate]);
}
