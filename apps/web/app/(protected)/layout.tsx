'use client';
import { usePrivy } from '@privy-io/react-auth';
import type { ReactNode } from 'react';

import { LoginButton } from '@/components/auth/login-button';
import { Skeleton } from '@/components/ui/skeleton';
import { useWalletSync } from '@/hooks/use-wallet-sync';

// Covers the gap proxy.ts leaves: a client-side navigation into this group never
// re-runs it. Neither layer is the security boundary -- requireAuth on the API is.
export default function ProtectedLayout({ children }: { children: ReactNode }) {
  const { ready, authenticated } = usePrivy();

  // Here rather than on the dashboard: this is the first protected thing that
  // renders after login, whichever page the user lands on.
  useWalletSync();

  if (!ready) {
    return (
      <div className="flex min-h-screen flex-col gap-4 p-8">
        <Skeleton className="h-9 w-40" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  // Reaching this means a client-side navigation got here without a session.
  if (!authenticated) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4">
        <p className="text-muted-foreground text-sm">You need to sign in to view this page.</p>
        <LoginButton />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b px-6 py-3">
        <span className="text-sm font-medium">Quant Platform</span>
        <LoginButton />
      </header>
      <main className="flex-1 p-6">{children}</main>
    </div>
  );
}
