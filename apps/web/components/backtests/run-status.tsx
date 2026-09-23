'use client';

import type { RunStatus } from '@quant/contracts/backtest';
import { RiCheckLine, RiCloseLine, RiLoader4Line } from '@remixicon/react';

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

export const STATUS_LABEL: Record<RunStatus, string> = {
  SUBMITTING: 'Waiting for the engine',
  QUEUED: 'Queued',
  FETCHING_DATA: 'Downloading market data',
  RUNNING: 'Running',
  SUCCEEDED: 'Succeeded',
  FAILED: 'Failed',
  CANCELLED: 'Cancelled',
};

const VARIANT: Record<RunStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  SUBMITTING: 'outline',
  QUEUED: 'outline',
  FETCHING_DATA: 'secondary',
  RUNNING: 'secondary',
  SUCCEEDED: 'default',
  FAILED: 'destructive',
  CANCELLED: 'outline',
};

export function StatusBadge({ status }: { status: RunStatus }) {
  const busy = status === 'FETCHING_DATA' || status === 'RUNNING';
  return (
    <Badge variant={VARIANT[status]}>
      {busy && <RiLoader4Line className="animate-spin" />}
      {STATUS_LABEL[status]}
    </Badge>
  );
}

const STEPS = ['QUEUED', 'FETCHING_DATA', 'RUNNING', 'SUCCEEDED'] as const;

/** The path a run takes. A step already passed is ticked, the current one spins. */
export function StatusTimeline({ status }: { status: RunStatus }) {
  const failed = status === 'FAILED' || status === 'CANCELLED';
  const at = STEPS.indexOf(status as (typeof STEPS)[number]); // -1 while SUBMITTING, or once failed.

  return (
    <ol className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-0">
      {STEPS.map((step, i) => {
        const done = at > i || status === 'SUCCEEDED';
        const current = at === i && status !== 'SUCCEEDED';
        return (
          <li key={step} className="flex items-center gap-2 sm:flex-1">
            <span
              className={cn(
                'flex size-6 shrink-0 items-center justify-center rounded-full border text-xs',
                done && 'border-primary bg-primary text-primary-foreground',
                current && 'border-primary text-primary'
              )}
            >
              {done ? (
                <RiCheckLine className="size-4" />
              ) : current ? (
                <RiLoader4Line className="size-4 animate-spin" />
              ) : (
                i + 1
              )}
            </span>
            <span className={cn('text-sm', !done && !current && 'text-muted-foreground')}>{STATUS_LABEL[step]}</span>
            {i < STEPS.length - 1 && <span className="mx-3 hidden h-px flex-1 bg-border sm:block" />}
          </li>
        );
      })}
      {failed && (
        <li className="flex items-center gap-2 text-sm text-destructive sm:ml-4">
          <RiCloseLine className="size-4" /> {STATUS_LABEL[status]}
        </li>
      )}
    </ol>
  );
}
