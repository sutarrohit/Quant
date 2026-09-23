'use client';
import { PrivyProvider } from '@privy-io/react-auth';
import { QueryClientProvider } from '@tanstack/react-query';

import { getQueryClient } from '@/lib/getQueryClient';
import env from '@/env';

import type * as React from 'react';
import { Toaster } from '@/components/ui/sonner';

import { ThemeProvider } from './theme-provider';

export default function Providers({ children }: { children: React.ReactNode }) {
  const queryClient = getQueryClient();

  return (
    // A client component, hence here rather than in the server-component layout.
    // `loginMethods` stays absent so the Privy dashboard remains the one place that
    // decision lives. `embeddedWallets` is per-chain and defaults to 'off', and
    // 'all-users' gives every user a wallet whose address we can rely on existing.
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
          <Toaster />
        </ThemeProvider>
      </QueryClientProvider>
    </PrivyProvider>
  );
}
