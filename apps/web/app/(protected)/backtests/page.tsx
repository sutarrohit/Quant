'use client';

import { RiFlaskLine } from '@remixicon/react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useState } from 'react';

import { BacktestCard } from '@/components/backtests/backtest-card';
import { CardGrid, CardGridSkeleton } from '@/components/metric-card';
import { EmptyState, ErrorState } from '@/components/page-states';
import { Button, buttonVariants } from '@/components/ui/button';
import { backtestsQueryOptions } from '@/lib/api/backtests/backtest-queries';

const PAGE_SIZE = 20;

export default function BacktestsPage() {
  const [page, setPage] = useState(1);
  const { data, isPending, error, refetch } = useQuery(backtestsQueryOptions({ page, pageSize: PAGE_SIZE }));

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Backtests</h1>
        <p className="text-sm text-muted-foreground">
          Every run, newest first. Results are kept after the engine forgets the job.
        </p>
      </div>

      {isPending && <CardGridSkeleton />}

      {error && <ErrorState error={error} title="Could not load runs" onRetry={() => void refetch()} />}

      {data && data.pagination.total === 0 && (
        <EmptyState
          icon={<RiFlaskLine />}
          title="No backtests yet"
          description="Open a strategy and run it over past data."
          action={
            <Link href="/strategies" className={buttonVariants()}>
              {' '}
              Go to strategies{' '}
            </Link>
          }
        />
      )}

      {data && data.data.length > 0 && (
        <>
          <CardGrid>
            {data.data.map((run) => (
              <BacktestCard key={run.id} run={run} />
            ))}
          </CardGrid>
          {data.pagination.totalPages > 1 && (
            <div className="flex items-center justify-end gap-3 text-sm text-muted-foreground">
              <span>
                Page {page} of {data.pagination.totalPages}
              </span>
              <Button variant="outline" size="sm" disabled={page === 1} onClick={() => setPage(page - 1)}>
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= data.pagination.totalPages}
                onClick={() => setPage(page + 1)}
              >
                Next
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
