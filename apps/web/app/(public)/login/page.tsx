'use client';
import { usePrivy } from '@privy-io/react-auth';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect } from 'react';

import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';

function LoginInner() {
  const { ready, authenticated, login } = usePrivy();
  const router = useRouter();
  const params = useSearchParams();

  // `redirect_uri` is set by proxy.ts when it turns someone away from a
  // protected route, so they land where they were headed rather than on `/`.
  const target = params.get('redirect_uri') ?? '/dashboard';

  useEffect(() => {
    if (ready && authenticated) router.replace(target);
  }, [ready, authenticated, router, target]);

  if (!ready) return <Skeleton className="h-10 w-32" />;

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6">
      <h1 className="text-2xl font-semibold">Sign in</h1>
      <p className="text-muted-foreground max-w-sm text-center text-sm">
        Privy hosts the sign-in flow. This page only launches it.
      </p>
      <Button onClick={login} disabled={authenticated}>
        Continue
      </Button>
    </div>
  );
}

export default function LoginPage() {
  // useSearchParams needs a Suspense boundary to avoid opting the whole route
  // into client-side rendering.
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  );
}
