'use client';

import type { Simulation, StrategyPhase } from '@quant/contracts/simulation';
import { RiArrowRightLine } from '@remixicon/react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';

import {
  CARD_CLASS,
  ChartWell,
  Metric,
  MetricGrid,
  shortTimeframe,
  symbolOf,
  toneOf,
  WellBadge,
} from '@/components/metric-card';
import { simState, StateBadge } from '@/components/simulations/state-badge';
import { buttonVariants } from '@/components/ui/button';
import { simulationEquityQueryOptions } from '@/lib/api/simulations/simulation-queries';
import { money, percent, timeAgo } from '@/lib/format';
import { cn } from '@/lib/utils';

const PHASE_LABEL: Record<StrategyPhase, string> = {
  WARMING_UP: 'Warming up',
  WAITING_FOR_ENTRY: 'Waiting for entry',
  IN_POSITION: 'In position',
};

const signedMoney = (value: string) => `${Number(value) > 0 ? '+' : ''}${money(value)}`;

export function SimulationCard({ sim }: { sim: Simulation }) {
  const client = useQueryClient();
  const equity = useQuery(simulationEquityQueryOptions(client, sim.id));
  const perf = sim.performance;
  const quote = perf?.quoteCurrency ?? '';
  const beat = sim.live?.observed?.heartbeatAt;
  const running = simState(sim).label === 'Running';

  const badge = perf?.stale ? (
    <WellBadge>Stale</WellBadge>
  ) : perf?.phase ? (
    <WellBadge>{PHASE_LABEL[perf.phase]}</WellBadge>
  ) : undefined;

  return (
    <div className={CARD_CLASS}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link href={`/simulations/${sim.id}`} className="block truncate text-base font-semibold hover:underline">
            {sim.name}
          </Link>
          <div className="text-muted-foreground mt-0.5 truncate text-xs">
            {symbolOf(sim.instrumentId)} {shortTimeframe(sim.barType)} · {sim.strategyName} v{sim.version}
          </div>
        </div>
        <div className="shrink-0">
          <StateBadge sim={sim} />
        </div>
      </div>

      <ChartWell
        values={equity.data?.points.map((p) => Number(p.equity))}
        up={Number(perf?.returnPercent ?? 0) >= 0}
        loading={equity.isPending && !equity.isError}
        empty={perf ? 'Equity appears after the first closed bar' : 'Not trading yet'}
        badge={badge}
      />

      <MetricGrid>
        <Metric label="Equity" value={perf?.equity ? `${money(perf.equity)} ${quote}` : '—'} />
        <Metric
          label="Return %"
          value={perf?.returnPercent ? percent(perf.returnPercent, true) : '—'}
          tone={toneOf(perf?.returnPercent)}
        />
        <Metric label="P&L" value={perf?.pnl ? `${signedMoney(perf.pnl)} ${quote}` : '—'} tone={toneOf(perf?.pnl)} />
        <Metric
          label="Position"
          value={perf?.position ? `${perf.position.side} ${perf.position.quantity}` : perf ? 'Flat' : '—'}
        />
      </MetricGrid>

      <div className="mt-auto flex items-center justify-between gap-2 pt-1">
        <span className="text-muted-foreground flex items-center gap-1.5 truncate text-xs" title={beat ?? undefined}>
          <span className="relative flex size-2">
            {running && <span className="absolute inset-0 animate-ping rounded-full bg-emerald-500/60" />}
            <span
              className={cn('relative size-2 rounded-full', running ? 'bg-emerald-500' : 'bg-muted-foreground/40')}
            />
          </span>
          {beat ? `Heartbeat ${timeAgo(beat)}` : 'No heartbeat yet'}
        </span>
        <Link href={`/simulations/${sim.id}`} className={buttonVariants({ variant: 'outline', size: 'sm' })}>
          Open <RiArrowRightLine />
        </Link>
      </div>
    </div>
  );
}
