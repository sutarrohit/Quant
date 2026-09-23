'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams, useSearchParams } from 'next/navigation';

import { SimulationForm } from '@/components/simulations/simulation-form';
import { ErrorState } from '@/components/page-states';
import { Skeleton } from '@/components/ui/skeleton';
import { strategyQueryOptions } from '@/lib/api/strategies/strategy-queries';
import { useStrategyBuilderStore } from '@/stores/strategy-builder';

export default function NewSimulationPage() {
  const { id } = useParams<{ id: string }>();
  const versionId = useSearchParams().get('version') ?? undefined; // Preselected from a backtest or version link.
  const { data, isPending, error, refetch } = useQuery(strategyQueryOptions(id));
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
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Paper trade {data.name}</h1>
        <p className="text-sm text-muted-foreground">
          Runs the same spec you backtested against live prices, with simulated fills.
          {hasDraft && ' Unsaved edits are not included: save them as a version first.'}
        </p>
      </div>
      <SimulationForm strategy={data} versionId={versionId} />
    </div>
  );
}
