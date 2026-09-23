'use client';

import { RiErrorWarningLine } from '@remixicon/react';
import Link from 'next/link';
import { useEffect } from 'react';

import { Button, buttonVariants } from '@/components/ui/button';

/** A page that threw. The sidebar stays, so the rest of the app is one click away. */
export default function ProtectedError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => console.error(error), [error]); // Keep the stack in the console for a bug report.

  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-4 py-16 text-center">
      <RiErrorWarningLine className="size-8 text-destructive" />
      <div className="flex flex-col gap-1">
        <h1 className="font-medium">This page hit an error</h1>
        <p className="text-sm text-muted-foreground">{error.message || 'Something went wrong while rendering it.'}</p>
        {error.digest && <p className="text-xs text-muted-foreground">Ref: {error.digest}</p>}
      </div>
      <div className="flex gap-2">
        <Button onClick={reset}>Try again</Button>
        <Link href="/strategies" className={buttonVariants({ variant: 'outline' })}>
          Go to strategies
        </Link>
      </div>
    </div>
  );
}
