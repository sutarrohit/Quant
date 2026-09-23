'use client';

import type { BacktestRun } from '@quant/contracts/backtest';
import Link from 'next/link';

import { StatusBadge } from '@/components/backtests/run-status';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { percent, timeAgo, utcDate } from '@/lib/format';

const timeframeOf = (barType: string) => barType.split('-').slice(1, 3).join(' ').toLowerCase(); // "15 minute"

export function RunTable({ runs, showStrategy = true }: { runs: BacktestRun[]; showStrategy?: boolean }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Status</TableHead>
          {showStrategy && <TableHead>Strategy</TableHead>}
          <TableHead>Market</TableHead>
          <TableHead>Window (UTC)</TableHead>
          <TableHead className="text-right">Return</TableHead>
          <TableHead>Started</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => {
          const ret = run.summary ? Number(run.summary.totalReturn) : null;
          return (
            <TableRow key={run.id} className="relative">
              <TableCell>
                {/* Stretched link: the whole row opens the run. */}
                <Link href={`/backtests/${run.id}`} className="absolute inset-0" aria-label="Open run" />
                <StatusBadge status={run.status} />
              </TableCell>
              {showStrategy && (
                <TableCell className="font-medium">
                  {run.strategyName} <span className="text-muted-foreground">v{run.version}</span>
                </TableCell>
              )}
              <TableCell>
                <span className="flex items-center gap-2">
                  {run.instrumentId.replace(/\.[A-Z]+$/, '')}
                  <Badge variant="outline">{timeframeOf(run.barType)}</Badge>
                </span>
              </TableCell>
              <TableCell className="text-muted-foreground">
                {utcDate(run.start)} → {utcDate(run.end)}
              </TableCell>
              <TableCell
                className={cn(
                  'text-right tabular-nums',
                  ret !== null && ret > 0 && 'text-emerald-700 dark:text-emerald-400',
                  ret !== null && ret < 0 && 'text-destructive'
                )}
              >
                {run.summary ? percent(run.summary.totalReturn, true) : '—'}
              </TableCell>
              <TableCell className="text-muted-foreground" title={run.submittedAt}>
                {timeAgo(run.submittedAt)}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
