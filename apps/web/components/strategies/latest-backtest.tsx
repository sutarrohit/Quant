'use client';

import { isTerminal } from '@quant/contracts/backtest';
import { RiArrowRightLine, RiFlaskLine, RiLoader4Line } from '@remixicon/react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';

import { BacktestMetrics } from '@/components/backtests/backtest-card';
import { ChartWell, WellBadge } from '@/components/metric-card';
import { SectionTitle } from '@/components/page-header';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { backtestsQueryOptions, equityQueryOptions } from '@/lib/api/backtests/backtest-queries';
import { utcDate } from '@/lib/format';

/** The newest successful backtest of one version, or a way to run the first. */
export function LatestBacktest({
  strategyId,
  versionId,
  version,
}: {
  strategyId: string;
  versionId: string;
  version: number;
}) {
  // Newest first; the list is per strategy, so pick this version's runs out of it.
  const runs = useQuery(backtestsQueryOptions({ strategyId, pageSize: 50 }));
  const mine = runs.data?.data.filter((r) => r.versionId === versionId) ?? [];
  const latest = mine.find((r) => r.status === 'SUCCEEDED') ?? null;
  const running = mine.some((r) => !isTerminal(r.status));
  const equity = useQuery(equityQueryOptions(latest?.id ?? '', latest !== null));
  const runHref = `/strategies/${strategyId}/backtest?version=${versionId}`;

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <CardTitle>
            <SectionTitle icon={RiFlaskLine}>Latest backtest of v{version}</SectionTitle>
          </CardTitle>
          <CardDescription>
            {latest
              ? `${latest.instrumentId.replace(/\.[A-Z]+$/, '')} · ${utcDate(latest.start)} → ${utcDate(latest.end)} UTC`
              : 'Replay this version over past bars to see how it would have done.'}
          </CardDescription>
        </div>
        {latest ? (
          <Link href={`/backtests/${latest.id}`} className={buttonVariants({ variant: 'outline', size: 'sm' })}>
            View report <RiArrowRightLine />
          </Link>
        ) : (
          <Link href={runHref} className={buttonVariants({ size: 'sm' })}>
            Run backtest <RiArrowRightLine />
          </Link>
        )}
      </CardHeader>
      <CardContent className="grid items-center gap-5 md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <ChartWell
          className="h-32"
          values={equity.data?.points.map((p) => Number(p.equity))}
          up={latest?.summary ? Number(latest.summary.totalReturn) >= 0 : true}
          loading={runs.isPending || (latest !== null && equity.isPending)}
          empty={latest ? 'No closed trades' : `No backtest of v${version} yet`}
          badge={
            running ? (
              <WellBadge>
                <RiLoader4Line className="size-3 animate-spin" /> Running
              </WellBadge>
            ) : undefined
          }
        />
        <BacktestMetrics summary={latest?.summary ?? null} />
      </CardContent>
    </Card>
  );
}
