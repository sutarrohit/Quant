'use client';

import { RiAddLine, RiArrowRightLine, RiCheckLine, RiFlaskLine, RiLineChartLine, RiPulseLine } from '@remixicon/react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import type { ComponentType, ReactNode } from 'react';

import { WalletAddress } from '@/components/auth/wallet-address';
import { BacktestCard } from '@/components/backtests/backtest-card';
import { Tile, toneOf } from '@/components/backtests/summary-tiles';
import { CardGrid, CardGridSkeleton } from '@/components/metric-card';
import { SectionTitle } from '@/components/page-header';
import { EmptyState, ErrorState } from '@/components/page-states';
import { SimulationCard } from '@/components/simulations/simulation-card';
import { simState } from '@/components/simulations/state-badge';
import { buttonVariants } from '@/components/ui/button';
import { backtestsQueryOptions } from '@/lib/api/backtests/backtest-queries';
import { simulationsQueryOptions } from '@/lib/api/simulations/simulation-queries';
import { strategiesQueryOptions } from '@/lib/api/strategies/strategy-queries';
import { percent } from '@/lib/format';
import { cn } from '@/lib/utils';

const RECENT = 3; // One row of cards at common laptop widths.

function Section({
  icon,
  tone,
  title,
  href,
  children,
}: {
  icon: ComponentType<{ className?: string }>;
  tone?: 'emerald' | 'cyan' | 'violet';
  title: string;
  href: string;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-semibold tracking-tight">
          <SectionTitle icon={icon} tone={tone}>
            {title}
          </SectionTitle>
        </h2>
        <Link href={href} className="text-muted-foreground hover:text-foreground flex items-center gap-1 text-sm">
          View all <RiArrowRightLine className="size-4" />
        </Link>
      </div>
      {children}
    </section>
  );
}

/** One step of the write → backtest → paper trade path, ticked once it has happened. */
function Step({ n, label, done, href }: { n: number; label: string; done: boolean | undefined; href: string }) {
  return (
    <Link
      href={href}
      className="bg-background/60 hover:border-emerald-500/40 flex flex-1 items-center gap-3 rounded-xl border px-4 py-3 backdrop-blur transition-colors"
    >
      <span
        className={cn(
          'flex size-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold',
          done ? 'border-emerald-500 bg-emerald-500 text-black' : 'text-muted-foreground'
        )}
      >
        {done ? <RiCheckLine className="size-4" /> : n}
      </span>
      <span className="text-sm font-medium">{label}</span>
    </Link>
  );
}

/** Where a sign-in lands: what exists, and the next thing to do. */
export default function DashboardPage() {
  const strategies = useQuery(strategiesQueryOptions());
  const runs = useQuery(backtestsQueryOptions({ page: 1, pageSize: RECENT }));
  const sims = useQuery(simulationsQueryOptions());

  const count = strategies.data?.strategies.length;
  const runTotal = runs.data?.pagination.total;
  const simList = sims.data?.simulations;
  const running = simList?.filter((s) => simState(s).label === 'Running').length;

  // Only over the runs on screen, and labelled so.
  const best = runs.data?.data
    .filter((r) => r.summary)
    .reduce<
      string | null
    >((top, r) => (top === null || Number(r.summary!.totalReturn) > Number(top) ? r.summary!.totalReturn : top), null);

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-8">
      <div className="relative isolate overflow-hidden rounded-3xl border bg-gradient-to-br from-emerald-500/15 via-transparent to-cyan-500/10 p-6 sm:p-8">
        <div
          aria-hidden
          className="absolute inset-0 -z-10 bg-[linear-gradient(to_right,var(--border)_1px,transparent_1px),linear-gradient(to_bottom,var(--border)_1px,transparent_1px)] bg-[size:40px_40px] [mask-image:radial-gradient(ellipse_at_top_right,black_20%,transparent_70%)]"
        />
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex flex-col gap-2">
            <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Overview</h1>
            <p className="text-muted-foreground max-w-xl text-sm">
              Write a strategy, backtest it on real Binance data, then paper trade the exact same spec.
            </p>
          </div>
          <div className="bg-background/60 rounded-xl border px-3 py-2 backdrop-blur">
            <WalletAddress />
          </div>
        </div>

        <div className="mt-6 flex flex-col gap-3 sm:flex-row">
          <Step n={1} label="Write a strategy" done={count !== undefined && count > 0} href="/strategies/new" />
          <Step n={2} label="Backtest it" done={runTotal !== undefined && runTotal > 0} href="/strategies" />
          <Step n={3} label="Paper trade it" done={simList !== undefined && simList.length > 0} href="/backtests" />
        </div>

        <div className="mt-6 flex flex-wrap gap-2">
          <Link href="/strategies/new" className={buttonVariants({ size: 'lg', className: 'px-4' })}>
            <RiAddLine /> New strategy
          </Link>
          <Link href="/strategies" className={buttonVariants({ size: 'lg', variant: 'outline', className: 'px-4' })}>
            <RiFlaskLine /> Run a backtest
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile size="lg" label="Strategies" value={count === undefined ? '—' : String(count)} hint="Saved rule sets" />
        <Tile
          size="lg"
          label="Backtests"
          value={runTotal === undefined ? '—' : String(runTotal)}
          hint="Every run is kept"
        />
        <Tile
          size="lg"
          label="Paper accounts"
          value={simList === undefined ? '—' : String(simList.length)}
          hint={running === undefined ? undefined : `${running} running`}
        />
        <Tile
          size="lg"
          label="Best recent return"
          value={best ? percent(best, true) : '—'}
          tone={best ? toneOf(best) : undefined}
          hint={`Of the last ${RECENT} backtests`}
        />
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

      <Section icon={RiFlaskLine} title="Recent backtests" href="/backtests">
        {runs.isPending && <CardGridSkeleton count={RECENT} />}
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
        {!!runs.data?.data.length && (
          <CardGrid>
            {runs.data.data.map((run) => (
              <BacktestCard key={run.id} run={run} />
            ))}
          </CardGrid>
        )}
      </Section>

      <Section icon={RiPulseLine} tone="cyan" title="Simulations" href="/simulations">
        {sims.isPending && <CardGridSkeleton count={2} />}
        {sims.error && (
          <ErrorState error={sims.error} title="Could not load simulations" onRetry={() => void sims.refetch()} />
        )}
        {simList?.length === 0 && (
          <EmptyState
            icon={<RiPulseLine />}
            title="No paper accounts"
            description="After a backtest you trust, paper trade it against live prices."
          />
        )}
        {!!simList?.length && (
          <CardGrid>
            {simList.slice(0, RECENT).map((sim) => (
              <SimulationCard key={sim.id} sim={sim} />
            ))}
          </CardGrid>
        )}
      </Section>
    </div>
  );
}
