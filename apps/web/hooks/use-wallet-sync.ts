'use client';
import { usePrivy, useWallets } from '@privy-io/react-auth';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

import { syncWalletsMutationOptions, walletsQueryOptions } from '@/lib/api/user/user-queries';

// Ethereum is EIP-55 checksummed and connectors vary the casing, so those compare
// case-insensitively. Everything else (Solana's base58) is case-significant.
const addressKey = (address: string) => (address.startsWith('0x') ? address.toLowerCase() : address);

/**
 * Tell the server a wallet has appeared, once Privy has created it in the browser.
 *
 * Never sends the address -- the server re-reads that from Privy. Fires only when
 * Privy reports a wallet the server has not returned, and each address is attempted
 * once per mount so a sync that comes back without it cannot loop.
 */
export function useWalletSync() {
  const { authenticated } = usePrivy();
  const { wallets, ready } = useWallets();
  // `enabled` matters: the protected layout also renders for a signed-out visitor
  // who navigated in on the client, whose first paint would fire a doomed request.
  const { data: stored } = useQuery({ ...walletsQueryOptions(), enabled: authenticated });
  const queryClient = useQueryClient();
  const attempted = useRef(new Set<string>());

  const { mutate } = useMutation({
    ...syncWalletsMutationOptions(),
    // The response is authoritative, so write it in rather than re-fetching.
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
