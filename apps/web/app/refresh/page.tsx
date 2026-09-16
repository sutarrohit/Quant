'use client';
import { getAccessToken, usePrivy } from '@privy-io/react-auth';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect } from 'react';

function RefreshInner() {
  const { ready, authenticated } = usePrivy();
  const router = useRouter();
  const params = useSearchParams();

  useEffect(() => {
    // Privy has not rehydrated yet; `authenticated` is not meaningful until it has.
    if (!ready) return;

    const target = params.get('redirect_uri') ?? '/';

    if (!authenticated) {
      router.replace(`/login?redirect_uri=${encodeURIComponent(target)}`);
      return;
    }

    // Re-mints the access token, which rewrites the privy-token cookie that
    // proxy.ts looks for. Only then is the redirect safe -- otherwise Proxy
    // would bounce us straight back here.
    void getAccessToken().then(() => router.replace(target));
  }, [ready, authenticated, params, router]);

  return <p className="text-muted-foreground text-sm">Restoring your session…</p>;
}

// Landing spot for "the session is alive but the access token expired". Reached
// only from proxy.ts; users never navigate here on purpose.
export default function RefreshPage() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Suspense fallback={null}>
        <RefreshInner />
      </Suspense>
    </div>
  );
}
