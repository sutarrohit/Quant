'use client';

import type { Simulation } from '@quant/contracts/simulation';
import Link from 'next/link';

import { StateBadge } from '@/components/simulations/state-badge';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { money, percent, timeAgo } from '@/lib/format';

const timeframeOf = (barType: string) => barType.split('-').slice(1, 3).join(' ').toLowerCase(); // "15 minute"

export function SimulationTable({ simulations }: { simulations: Simulation[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>State</TableHead>
          <TableHead>Strategy</TableHead>
          <TableHead>Market</TableHead>
          <TableHead className="text-right">Equity</TableHead>
          <TableHead className="text-right">Return</TableHead>
          <TableHead>Position</TableHead>
          <TableHead>Last heartbeat</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {simulations.map((sim) => {
          const beat = sim.live?.observed?.heartbeatAt;
          const perf = sim.performance;
          const ret = perf?.returnPercent ? Number(perf.returnPercent) : null;
          return (
            <TableRow key={sim.id} className="relative">
              <TableCell className="font-medium">
                {/* Stretched link: the whole row opens the simulation. */}
                <Link href={`/simulations/${sim.id}`} className="absolute inset-0" aria-label={`Open ${sim.name}`} />
                {sim.name}
              </TableCell>
              <TableCell>
                <StateBadge sim={sim} />
              </TableCell>
              <TableCell>
                {sim.strategyName} <span className="text-muted-foreground">v{sim.version}</span>
              </TableCell>
              <TableCell>
                <span className="flex items-center gap-2">
                  {sim.instrumentId.replace(/\.[A-Z]+$/, '')}
                  <Badge variant="outline">{timeframeOf(sim.barType)}</Badge>
                </span>
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {perf?.equity ? `${money(perf.equity)} ${perf.quoteCurrency ?? ''}` : '—'}
              </TableCell>
              <TableCell
                className={cn(
                  'text-right tabular-nums',
                  ret !== null && ret > 0 && 'text-emerald-700 dark:text-emerald-400',
                  ret !== null && ret < 0 && 'text-destructive'
                )}
              >
                {ret !== null ? percent(ret, true) : '—'}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {perf?.position ? `${perf.position.side} ${perf.position.quantity}` : perf ? 'Flat' : '—'}
              </TableCell>
              <TableCell className="text-muted-foreground" title={beat ?? undefined}>
                {beat ? timeAgo(beat) : '—'}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
