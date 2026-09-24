'use client';

import type { BacktestRun, BacktestSummary } from '@quant/contracts/backtest';
import { RiArrowRightLine, RiErrorWarningLine, RiLoader4Line } from '@remixicon/react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';

import { STATUS_LABEL, StatusBadge } from '@/components/backtests/run-status';
import {
  CARD_CLASS,
  ChartWell,
  Metric,
  MetricGrid,
  Pill,
  shortTimeframe,
  symbolOf,
  toneOf,
  WellBadge,
} from '@/components/metric-card';
import { buttonVariants } from '@/components/ui/button';
import { equityQueryOptions } from '@/lib/api/backtests/backtest-queries';
import { percent, utcDate } from '@/lib/format';

/** Net P&L, drawdown, win rate, PF / trades. Also used by the strategy card. */
export function BacktestMetrics({ summary }: { summary: BacktestSummary | null }) {
  return (
    <MetricGrid>
      <Metric
        label="Net P&L %"
        value={summary ? percent(summary.totalReturn, true) : '—'}
        tone={summary ? (toneOf(summary.totalReturn) ?? 'up') : undefined}
      />
      <Metric
        label="Max DD %"
        value={summary ? percent(summary.maxDrawdown) : '—'}
        tone={summary ? 'down' : undefined}
      />
      <Metric label="Win rate" value={summary ? percent(summary.winRate) : '—'} />
      <Metric
        label="PF / Trades"
        value={summary ? `${Number(summary.profitFactor).toFixed(2)} / ${summary.tradeCount}` : '—'}
      />
    </MetricGrid>
  );
}

export function BacktestCard({ run }: { run: BacktestRun }) {
  const done = run.status === 'SUCCEEDED';
  const equity = useQuery(equityQueryOptions(run.id, done));
  const up = run.summary ? Number(run.summary.totalReturn) >= 0 : true;

  const empty = done ? (
    'No closed trades'
  ) : run.status === 'FAILED' ? (
    <span className="flex items-center gap-1 text-red-600 dark:text-red-400">
      <RiErrorWarningLine className="size-3.5 shrink-0" />
      <span className="line-clamp-2">{run.error?.message ?? 'Failed'}</span>
    </span>
  ) : run.status === 'CANCELLED' ? (
    'Cancelled'
  ) : (
    <span className="flex items-center gap-1.5">
      <RiLoader4Line className="size-3.5 animate-spin" /> {STATUS_LABEL[run.status]}…
    </span>
  );

  return (
    <div className={CARD_CLASS}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-base font-semibold">{run.strategyName}</div>
          <div className="text-muted-foreground mt-0.5 truncate text-xs">
            {symbolOf(run.instrumentId)} {shortTimeframe(run.barType)}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Pill>V{run.version}</Pill>
          {!done && <StatusBadge status={run.status} />}
        </div>
      </div>

      <ChartWell
        values={equity.data?.points.map((p) => Number(p.equity))}
        up={up}
        loading={done && equity.isPending}
        empty={empty}
        badge={run.summary?.openPositions ? <WellBadge>{run.summary.openPositions} still open</WellBadge> : undefined}
      />

      <BacktestMetrics summary={run.summary} />

      <div className="mt-auto flex items-center justify-between gap-2 pt-1">
        <span className="text-muted-foreground truncate text-xs" title="UTC">
          {utcDate(run.start)} → {utcDate(run.end)}
        </span>
        <Link href={`/backtests/${run.id}`} className={buttonVariants({ variant: 'outline', size: 'sm' })}>
          {done ? 'View report' : 'Open'} <RiArrowRightLine />
        </Link>
      </div>
    </div>
  );
}
