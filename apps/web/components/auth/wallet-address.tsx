'use client';
import { usePrivy, useWallets } from '@privy-io/react-auth';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';

// Addresses are 42 characters and unreadable in full. Truncating to head+tail is
// the convention, and it is still enough to verify against another display.
const truncate = (address: string) => `${address.slice(0, 6)}…${address.slice(-4)}`;

export function WalletAddress() {
  const { ready: privyReady, authenticated } = usePrivy();
  // `ready` here is separate from usePrivy's: wallets resolve after auth does,
  // so checking only the auth one renders an empty list for a moment.
  const { wallets, ready: walletsReady } = useWallets();
  const [copied, setCopied] = useState(false);

  if (!privyReady || !walletsReady) return <Skeleton className="h-8 w-40" />;
  if (!authenticated) return null;

  const wallet = wallets[0];

  // Not an error state. `createOnLogin: 'users-without-wallets'` prompts rather
  // than creating silently, so a user who dismissed that prompt lands here.
  if (!wallet) {
    return <p className="text-muted-foreground text-sm">No wallet linked yet.</p>;
  }

  const copy = async () => {
    await navigator.clipboard.writeText(wallet.address);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="flex items-center gap-2">
      <code className="bg-muted rounded px-2 py-1 text-sm" title={wallet.address}>
        {truncate(wallet.address)}
      </code>
      <span className="text-muted-foreground text-xs">
        {/* 'privy' here means the embedded wallet; anything else is one the user connected. */}
        {wallet.walletClientType === 'privy' ? 'embedded' : wallet.walletClientType}
      </span>
      <Button variant="ghost" size="sm" onClick={copy}>
        {copied ? 'Copied' : 'Copy'}
      </Button>
    </div>
  );
}
