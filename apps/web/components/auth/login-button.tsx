'use client';
import { usePrivy } from '@privy-io/react-auth';

import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';

// Privy hosts the entire login flow in a modal, so there is no login page or
// form to build here.
export function LoginButton() {
  const { ready, authenticated, user, login, logout } = usePrivy();

  // `ready` is false while Privy rehydrates the session. Checking `authenticated`
  // before then shows a signed-out flash to an already-signed-in user.
  if (!ready) return <Skeleton className="h-9 w-24" />;

  if (!authenticated) return <Button onClick={login}>Sign in</Button>;

  // A wallet-only user has no email, so fall back through the linked accounts
  // rather than assuming one exists.
  const label = user?.email?.address ?? user?.wallet?.address ?? 'Account';

  return (
    <Button variant="ghost" onClick={logout} title={label}>
      <span className="max-w-[16ch] truncate">{label}</span>
    </Button>
  );
}
