'use client';

import { RiErrorWarningLine } from '@remixicon/react';
import Link from 'next/link';
import type { ReactNode } from 'react';

import { Button } from '@/components/ui/button';
import { ApiError } from '@/utils/api-error';

/** Nothing here yet, and the one thing to do about it. */
export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-16 text-center">
      <span className="text-muted-foreground [&_svg]:size-8">{icon}</span>
      <div>
        <p className="font-medium">{title}</p>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  );
}

/**
 * A request that failed. Carries the request id, so a screenshot of it can be traced
 * through Hono and the engine. `notFound` swaps in calmer copy for a 404.
 */
export function ErrorState({
  error,
  title,
  onRetry,
  back,
  notFound,
}: {
  error: unknown;
  title: string;
  onRetry?: () => void;
  back?: { href: string; label: string };
  notFound?: { code: string; title: string; description: string };
}) {
  const api = error instanceof ApiError ? error : null;
  const missing = notFound && api?.code === notFound.code;
  const message = error instanceof Error ? error.message : 'Something went wrong.';

  return (
    <div role="alert" className="mx-auto flex max-w-md flex-col items-center gap-3 py-16 text-center">
      {!missing && <RiErrorWarningLine className="size-8 text-destructive" />}
      <div className="flex flex-col gap-1">
        <p className="font-medium">{missing ? notFound.title : title}</p>
        <p className="text-sm text-muted-foreground">{missing ? notFound.description : message}</p>
        {!missing && api?.requestId && <p className="text-xs text-muted-foreground">Ref: {api.requestId}</p>}
      </div>
      <div className="flex gap-2">
        {!missing && onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry}>
            Try again
          </Button>
        )}
        {back && (
          <Link href={back.href} className="self-center text-sm underline underline-offset-2">
            {back.label}
          </Link>
        )}
      </div>
    </div>
  );
}
