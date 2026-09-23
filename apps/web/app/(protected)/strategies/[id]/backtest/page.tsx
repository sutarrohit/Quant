'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useParams, useSearchParams } from 'next/navigation';

import { BacktestForm } from '@/components/backtests/backtest-form';
import { Skeleton } from '@/components/ui/skeleton';
import { strategyQueryOptions } from '@/lib/api/strategies/strategy-queries';
import { useStrategyBuilderStore } from '@/stores/strategy-builder';

export default function NewBacktestPage() {
  const { id } = useParams<{ id: string }>();
  const versionId = useSearchParams().get('version') ?? undefined; // Preselected from a version link.
  const { data, isPending, error } = useQuery(strategyQueryOptions(id));
  const hasDraft = useStrategyBuilderStore((s) => !!s.drafts[id]);

  if (isPending) {
    return (
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  if (error || !data || data.versions.length === 0) {
    return (
      <div className="mx-auto flex max-w-md flex-col items-center gap-3 py-16 text-center">
        <p className="font-medium">Could not load this strategy</p>
        <p className="text-sm text-muted-foreground">{error?.message ?? 'It has no saved version.'}</p>
        <Link href="/strategies" className="text-sm underline underline-offset-2">
          Back to strategies
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Backtest {data.name}</h1>
        <p className="text-sm text-muted-foreground">
          Replays the rules over past bars, with fees and slippage charged on every fill.
          {hasDraft && ' Unsaved edits are not included: save them as a version first.'}
        </p>
      </div>
      <BacktestForm strategy={data} versionId={versionId} />
    </div>
  );
}
