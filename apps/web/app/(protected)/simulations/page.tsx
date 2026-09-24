'use client';

import { RiPulseLine } from '@remixicon/react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';

import { CardGrid, CardGridSkeleton } from '@/components/metric-card';
import { SimulationCard } from '@/components/simulations/simulation-card';
import { EmptyState, ErrorState } from '@/components/page-states';
import { buttonVariants } from '@/components/ui/button';
import { simulationsQueryOptions } from '@/lib/api/simulations/simulation-queries';

export default function SimulationsPage() {
  const { data, isPending, error, refetch } = useQuery(simulationsQueryOptions());

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Simulations</h1>
        <p className="text-sm text-muted-foreground">Paper accounts trading live prices. Updates every 5 seconds.</p>
      </div>

      {isPending && <CardGridSkeleton />}

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

      {data && data.simulations.length > 0 && (
        <CardGrid>
          {data.simulations.map((sim) => (
            <SimulationCard key={sim.id} sim={sim} />
          ))}
        </CardGrid>
      )}
    </div>
  );
}
