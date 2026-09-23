'use client';

import { RiFlaskLine } from '@remixicon/react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useState } from 'react';

import { RunTable } from '@/components/backtests/run-table';
import { Button, buttonVariants } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { backtestsQueryOptions } from '@/lib/api/backtests/backtest-queries';

const PAGE_SIZE = 20;

export default function BacktestsPage() {
  const [page, setPage] = useState(1);
  const { data, isPending, error, refetch } = useQuery(backtestsQueryOptions({ page, pageSize: PAGE_SIZE }));

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Backtests</h1>
        <p className="text-sm text-muted-foreground">
          Every run, newest first. Results are kept after the engine forgets the job.
        </p>
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
          <p className="text-sm text-destructive">Could not load runs: {error.message}</p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      )}

      {data && data.pagination.total === 0 && (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-16 text-center">
          <RiFlaskLine className="size-8 text-muted-foreground" />
          <div>
            <p className="font-medium">No backtests yet</p>
            <p className="text-sm text-muted-foreground">Open a strategy and run it over past data.</p>
          </div>
          <Link href="/strategies" className={buttonVariants()}>
            Go to strategies
          </Link>
        </div>
      )}

      {data && data.data.length > 0 && (
        <>
          <RunTable runs={data.data} />
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
