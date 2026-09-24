'use client';
import { useLogin, usePrivy } from '@privy-io/react-auth';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useRef, type ReactNode } from 'react';

// Navigates if signed in, otherwise opens the Privy modal and navigates once login completes.
function useAuthNavigate() {
  const { authenticated } = usePrivy();
  const router = useRouter();
  // onComplete also fires on mount for returning users, so only act on a login we started.
  const pending = useRef<string | null>(null);

  const { login } = useLogin({
    onComplete: ({ wasAlreadyAuthenticated }) => {
      const target = pending.current;
      pending.current = null;
      if (target && !wasAlreadyAuthenticated) router.push(target);
    },
    onError: () => {
      pending.current = null;
    },
  });

  return (href: string) => {
    if (authenticated) return router.push(href);
    pending.current = href;
    login();
  };
}

export function AuthLink({ href, className, children }: { href: string; className?: string; children: ReactNode }) {
  const go = useAuthNavigate();
  return (
    <button type="button" className={className} onClick={() => go(href)}>
      {children}
    </button>
  );
}

// Hidden once signed in, since "Open app" already covers that case.
export function SignInButton({ className }: { className?: string }) {
  const { ready, authenticated } = usePrivy();
  const go = useAuthNavigate();
  if (!ready || authenticated) return null;
  return (
    <button type="button" className={className} onClick={() => go('/dashboard')}>
      Sign in
    </button>
  );
}

// proxy.ts sends signed-out visitors here with ?redirect_uri=; open the modal for them.
export function LoginFromRedirect() {
  const { ready, authenticated } = usePrivy();
  const params = useSearchParams();
  const go = useAuthNavigate();
  const target = params.get('redirect_uri');
  const opened = useRef(false);

  useEffect(() => {
    if (!ready || !target || opened.current) return;
    opened.current = true;
    go(target);
  }, [ready, authenticated, target, go]);

  return null;
}
