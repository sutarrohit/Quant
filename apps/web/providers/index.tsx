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
    // `loginMethods` is deliberately still absent: it can only narrow the set
    // enabled in the Privy dashboard, so the dashboard stays the single place
    // that decision lives. Enabling Google there needed no change here.
    //
    // `embeddedWallets` is per-chain, not flat, and defaults to 'off' -- which is
    // why no wallet existed before this.
    //
    // 'all-users', not 'users-without-wallets': every user gets a Privy embedded
    // wallet regardless of how they signed in, including users who connected an
    // external wallet of their own. The platform needs one wallet per user whose
    // address it can rely on existing, rather than one that may or may not be
    // there depending on login method.
    //
    // Solana is one more key alongside `ethereum` if it is ever needed.
    <PrivyProvider
      appId={env.NEXT_PUBLIC_PRIVY_APP_ID}
      clientId={env.NEXT_PUBLIC_PRIVY_CLIENT_ID}
      config={{
        embeddedWallets: {
          ethereum: { createOnLogin: 'all-users' },
        },
      }}
    >
      <QueryClientProvider client={queryClient}>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          {children}
        </ThemeProvider>
      </QueryClientProvider>
    </PrivyProvider>
  );
}
