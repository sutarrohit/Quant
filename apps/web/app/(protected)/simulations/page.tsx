'use client';

import { RiPulseLine } from '@remixicon/react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';

import { SimulationTable } from '@/components/simulations/simulation-table';
import { Button, buttonVariants } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { simulationsQueryOptions } from '@/lib/api/simulations/simulation-queries';

export default function SimulationsPage() {
  const { data, isPending, error, refetch } = useQuery(simulationsQueryOptions());

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Simulations</h1>
        <p className="text-sm text-muted-foreground">Paper accounts trading live prices. Updates every 5 seconds.</p>
      </div>

      {isPending && (
        <div className="flex flex-col gap-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      )}

      {error && (
        <div className="flex flex-col items-start gap-3 rounded-lg border border-destructive/40 p-4">
          <p className="text-sm text-destructive">Could not load simulations: {error.message}</p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      )}

      {data && data.simulations.length === 0 && (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-16 text-center">
          <RiPulseLine className="size-8 text-muted-foreground" />
          <div>
            <p className="font-medium">No simulations yet</p>
            <p className="text-sm text-muted-foreground">Backtest a strategy, then paper trade it from there.</p>
          </div>
          <Link href="/strategies" className={buttonVariants()}>
            Go to strategies
          </Link>
        </div>
      )}

      {data && data.simulations.length > 0 && <SimulationTable simulations={data.simulations} />}
    </div>
  );
}
