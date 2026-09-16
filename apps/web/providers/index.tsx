'use client';
import { PrivyProvider } from '@privy-io/react-auth';
import { QueryClientProvider } from '@tanstack/react-query';

import { getQueryClient } from '@/lib/getQueryClient';
import env from '@/env';

import type * as React from 'react';
import { ThemeProvider } from './theme-provider';

export default function Providers({ children }: { children: React.ReactNode }) {
  const queryClient = getQueryClient();

  return (
    // PrivyProvider is a client component, which is why it lives here rather
    // than in app/layout.tsx (a server component). It wraps the query client so
    // any future auth-aware query can read Privy state.
    //
    // No `config` is passed deliberately:
    //   - `loginMethods` can only narrow the set enabled in the Privy dashboard,
    //     so the dashboard stays the single place login methods are decided.
    //   - `embeddedWallets` defaults to 'off'. Turning it on is a product
    //     decision (docs/privy-auth-integration.md section 7.2), and its real
    //     shape is per-chain: { ethereum: { createOnLogin: 'users-without-wallets' } }.
    <PrivyProvider appId={env.NEXT_PUBLIC_PRIVY_APP_ID} clientId={env.NEXT_PUBLIC_PRIVY_CLIENT_ID}>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          {children}
        </ThemeProvider>
      </QueryClientProvider>
    </PrivyProvider>
  );
}
