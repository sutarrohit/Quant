'use client';
import { useQuery } from '@tanstack/react-query';

import { WalletAddress } from '@/components/auth/wallet-address';
import { onboardingStatusQueryOptions } from '@/lib/api/user/user-queries';

// Proves the full path: proxy.ts, the rewrite, and requireAuth on the API.
export default function DashboardPage() {
  const { data, isPending, error } = useQuery(onboardingStatusQueryOptions());

  return (
    <div className="space-y-2">
      <h1 className="text-xl font-semibold">Dashboard</h1>
      <WalletAddress />
      {isPending && <p className="text-muted-foreground text-sm">Loading…</p>}
      {error && <p className="text-destructive text-sm">{error.message}</p>}
      {data && (
        <p className="text-muted-foreground text-sm">
          Onboarding {data.completed ? 'complete' : 'not complete'}.
        </p>
      )}
    </div>
  );
}
