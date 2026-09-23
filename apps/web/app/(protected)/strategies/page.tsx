'use client';

import { RiAddLine, RiLineChartLine } from '@remixicon/react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';

import { StrategyTable } from '@/components/strategies/strategy-table';
import { Button, buttonVariants } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { strategiesQueryOptions } from '@/lib/api/strategies/strategy-queries';

const newStrategy = (
  <Link href="/strategies/new" className={buttonVariants()}>
    <RiAddLine />
    New strategy
  </Link>
);

export default function StrategiesPage() {
  const { data, isPending, error, refetch } = useQuery(strategiesQueryOptions());

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Strategies</h1>
          <p className="text-sm text-muted-foreground">Rules you can backtest and run in simulation.</p>
        </div>
        {data && data.strategies.length > 0 && newStrategy}
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
          <p className="text-sm text-destructive">Could not load strategies: {error.message}</p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      )}

      {data && data.strategies.length === 0 && (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-16 text-center">
          <RiLineChartLine className="size-8 text-muted-foreground" />
          <div>
            <p className="font-medium">No strategies yet</p>
            <p className="text-sm text-muted-foreground">
              Write your first rule set, then backtest it against real market data.
            </p>
          </div>
          {newStrategy}
        </div>
      )}

      {data && data.strategies.length > 0 && <StrategyTable strategies={data.strategies} />}
    </div>
  );
}
