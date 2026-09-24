'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams, useSearchParams } from 'next/navigation';

import { BacktestForm } from '@/components/backtests/backtest-form';
import { Chip, PageHeader } from '@/components/page-header';
import { ErrorState } from '@/components/page-states';
import { Skeleton } from '@/components/ui/skeleton';
import { strategyQueryOptions } from '@/lib/api/strategies/strategy-queries';
import { useStrategyBuilderStore } from '@/stores/strategy-builder';

export default function NewBacktestPage() {
  const { id } = useParams<{ id: string }>();
  const versionId = useSearchParams().get('version') ?? undefined; // Preselected from a version link.
  const { data, isPending, error, refetch } = useQuery(strategyQueryOptions(id));
  const hasDraft = useStrategyBuilderStore((s) => !!s.drafts[id]);

  if (isPending) {
    return (
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-96 w-full rounded-2xl" />
      </div>
    );
  }

  if (error || !data || data.versions.length === 0) {
    return (
      <ErrorState
        error={error ?? new Error('It has no saved version.')}
        title="Could not load this strategy"
        onRetry={() => void refetch()}
        back={{ href: '/strategies', label: 'Back to strategies' }}
        notFound={{
          code: 'STRATEGY_NOT_FOUND',
          title: 'Strategy not found',
          description: 'It may have been archived.',
        }}
      />
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <PageHeader
        back={{ href: `/strategies/${id}`, label: data.name }}
        title={`Backtest ${data.name}`}
        chips={
          <>
            <Chip>Binance · Spot</Chip>
            <Chip>Replays the rules over past bars, with fees and slippage on every fill</Chip>
            {hasDraft && (
              <Chip className="border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400">
                Unsaved edits are not included: save them as a version first
              </Chip>
            )}
          </>
        }
      />
      <BacktestForm strategy={data} versionId={versionId} />
    </div>
  );
}
