'use client';

import { RiPulseLine } from '@remixicon/react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';

import { SimulationTable } from '@/components/simulations/simulation-table';
import { EmptyState, ErrorState, TableSkeleton } from '@/components/page-states';
import { buttonVariants } from '@/components/ui/button';
import { simulationsQueryOptions } from '@/lib/api/simulations/simulation-queries';

export default function SimulationsPage() {
  const { data, isPending, error, refetch } = useQuery(simulationsQueryOptions());

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Simulations</h1>
        <p className="text-sm text-muted-foreground">Paper accounts trading live prices. Updates every 5 seconds.</p>
      </div>

      {isPending && <TableSkeleton />}

      {error && <ErrorState error={error} title="Could not load simulations" onRetry={() => void refetch()} />}

      {data && data.simulations.length === 0 && (
        <EmptyState
          icon={<RiPulseLine />}
          title="No simulations yet"
          description="Backtest a strategy, then paper trade it from there."
          action={
            <Link href="/strategies" className={buttonVariants()}>
              {' '}
              Go to strategies{' '}
            </Link>
          }
        />
      )}

      {data && data.simulations.length > 0 && <SimulationTable simulations={data.simulations} />}
    </div>
  );
}
