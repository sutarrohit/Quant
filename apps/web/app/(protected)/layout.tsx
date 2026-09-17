'use client';
import { usePrivy } from '@privy-io/react-auth';
import type { ReactNode } from 'react';

import { LoginButton } from '@/components/auth/login-button';
import { Skeleton } from '@/components/ui/skeleton';
import { useWalletSync } from '@/hooks/use-wallet-sync';

// Second layer behind proxy.ts, not a replacement for it.
//
// Proxy runs on the server for full page loads, but a client-side
// navigation into this group does not re-run it. This guard covers that gap and
// prevents a flash of protected chrome while Privy rehydrates. Neither layer is
// the security boundary -- requireAuth on the API is.
export default function ProtectedLayout({ children }: { children: ReactNode }) {
  const { ready, authenticated } = usePrivy();

  // Here rather than on the dashboard: the wallet is created at first login, and
  // this layout is the first protected thing that renders afterwards, whichever
  // page the user lands on. It renders nothing and no-ops once the wallet is
  // stored -- see the hook for why the browser only signals, never supplies the
  // address.
  useWalletSync();

  if (!ready) {
    return (
      <div className="flex min-h-screen flex-col gap-4 p-8">
        <Skeleton className="h-9 w-40" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  // Middleware normally redirects before this renders. Reaching it means a
  // client-side navigation got here without a session; say so rather than
  // rendering an empty shell.
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
