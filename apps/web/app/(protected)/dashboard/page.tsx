'use client';

import { RiAddLine, RiFlaskLine, RiLineChartLine, RiPulseLine } from '@remixicon/react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import type { ReactNode } from 'react';

import { WalletAddress } from '@/components/auth/wallet-address';
import { RunTable } from '@/components/backtests/run-table';
import { EmptyState, ErrorState, TableSkeleton } from '@/components/page-states';
import { SimulationTable } from '@/components/simulations/simulation-table';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { backtestsQueryOptions } from '@/lib/api/backtests/backtest-queries';
import { simulationsQueryOptions } from '@/lib/api/simulations/simulation-queries';
import { strategiesQueryOptions } from '@/lib/api/strategies/strategy-queries';

function Section({ title, href, children }: { title: string; href: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle>{title}</CardTitle>
        <Link href={href} className="text-sm text-muted-foreground underline-offset-2 hover:underline">
          View all
        </Link>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

/** Where a sign-in lands: what exists, and the next thing to do. */
export default function DashboardPage() {
  const strategies = useQuery(strategiesQueryOptions());
  const runs = useQuery(backtestsQueryOptions({ page: 1, pageSize: 5 }));
  const sims = useQuery(simulationsQueryOptions());
  const count = strategies.data?.strategies.length;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Overview</h1>
          <p className="text-sm text-muted-foreground">
            {count === undefined
              ? 'Your strategies, backtests and paper accounts.'
              : `${count} ${count === 1 ? 'strategy' : 'strategies'}. Write one, backtest it, then paper trade it.`}
          </p>
        </div>
        <Link href="/strategies/new" className={buttonVariants()}>
          <RiAddLine /> New strategy
        </Link>
      </div>

      {strategies.error && (
        <ErrorState
          error={strategies.error}
          title="Could not load strategies"
          onRetry={() => void strategies.refetch()}
        />
      )}
      {count === 0 && (
        <EmptyState
          icon={<RiLineChartLine />}
          title="Start with a strategy"
          description="Entry and exit rules, a market and a risk per trade. The builder checks it as you go."
        />
      )}

      <Section title="Recent backtests" href="/backtests">
        {runs.isPending && <TableSkeleton />}
        {runs.error && (
          <ErrorState error={runs.error} title="Could not load backtests" onRetry={() => void runs.refetch()} />
        )}
        {runs.data?.data.length === 0 && (
          <EmptyState
            icon={<RiFlaskLine />}
            title="No backtests yet"
            description="Open a strategy and run it over past data."
          />
        )}
        {!!runs.data?.data.length && <RunTable runs={runs.data.data} />}
      </Section>

      <Section title="Simulations" href="/simulations">
        {sims.isPending && <TableSkeleton rows={2} />}
        {sims.error && (
          <ErrorState error={sims.error} title="Could not load simulations" onRetry={() => void sims.refetch()} />
        )}
        {sims.data?.simulations.length === 0 && (
          <EmptyState
            icon={<RiPulseLine />}
            title="No paper accounts"
            description="After a backtest you trust, paper trade it against live prices."
          />
        )}
        {!!sims.data?.simulations.length && <SimulationTable simulations={sims.data.simulations.slice(0, 5)} />}
      </Section>

      <WalletAddress />
    </div>
  );
}
