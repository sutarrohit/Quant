'use client';

import { RiAddLine, RiLineChartLine } from '@remixicon/react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';

import { StrategyTable } from '@/components/strategies/strategy-table';
import { EmptyState, ErrorState, TableSkeleton } from '@/components/page-states';
import { buttonVariants } from '@/components/ui/button';
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

      {isPending && <TableSkeleton />}

      {error && <ErrorState error={error} title="Could not load strategies" onRetry={() => void refetch()} />}

      {data && data.strategies.length === 0 && (
        <EmptyState
          icon={<RiLineChartLine />}
          title="No strategies yet"
          description="Write your first rule set, then backtest it against real market data."
          action={newStrategy}
        />
      )}

      {data && data.strategies.length > 0 && <StrategyTable strategies={data.strategies} />}
    </div>
  );
}
