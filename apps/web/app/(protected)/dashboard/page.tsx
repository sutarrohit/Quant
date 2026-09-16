'use client';
import { useQuery } from '@tanstack/react-query';

import { onboardingStatusQueryOptions } from '@/lib/api/user/user-queries';

// Minimal protected page. Its real purpose is to prove the full path end to end:
// proxy.ts lets the request through, the rewrite forwards the privy-token cookie,
// and requireAuth on the API verifies it and resolves the local user row.
export default function DashboardPage() {
  const { data, isPending, error } = useQuery(onboardingStatusQueryOptions());

  return (
    <div className="space-y-2">
      <h1 className="text-xl font-semibold">Dashboard</h1>
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
