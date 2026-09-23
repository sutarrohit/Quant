'use client';

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { tradesQueryOptions } from '@/lib/api/backtests/backtest-queries';
import { cn } from '@/lib/utils';
import { duration, money, percent, utcDateTime } from '@/lib/format';

const PAGE = 25;

/** Closed trades, a page at a time from the server. Costs per trade, so the total is traceable. */
export function TradeTable({ runId }: { runId: string }) {
  const [offset, setOffset] = useState(0);
  const { data, isPending, error, isPlaceholderData } = useQuery(tradesQueryOptions(runId, offset, PAGE, true));

  if (isPending) return <Skeleton className="h-64 w-full" />;
  if (error) return <p className="text-sm text-destructive">Could not load trades: {error.message}</p>;
  if (data.total === 0) return <p className="py-8 text-center text-sm text-muted-foreground">No closed trades.</p>;

  const last = Math.min(offset + PAGE, data.total);

  return (
    <div className={cn('flex flex-col gap-3', isPlaceholderData && 'opacity-60')}>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Entry (UTC)</TableHead>
            <TableHead>Exit (UTC)</TableHead>
            <TableHead>Side</TableHead>
            <TableHead className="text-right">Qty</TableHead>
            <TableHead className="text-right">Entry</TableHead>
            <TableHead className="text-right">Exit</TableHead>
            <TableHead className="text-right">PnL</TableHead>
            <TableHead className="text-right">Return</TableHead>
            <TableHead className="text-right">Fees</TableHead>
            <TableHead className="text-right">Slippage</TableHead>
            <TableHead className="text-right">Held</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.rows.map((t, i) => {
            const pnl = Number(t.pnl);
            return (
              <TableRow key={`${t.entryTime}-${i}`} className="tabular-nums">
                <TableCell>{utcDateTime(t.entryTime)}</TableCell>
                <TableCell>{utcDateTime(t.exitTime)}</TableCell>
                <TableCell>
                  <Badge variant="outline">{t.side}</Badge>
                </TableCell>
                <TableCell className="text-right">{t.quantity}</TableCell>
                <TableCell className="text-right">{t.entryPrice}</TableCell>
                <TableCell className="text-right">{t.exitPrice}</TableCell>
                <TableCell
                  className={cn(
                    'text-right',
                    pnl > 0 && 'text-emerald-600 dark:text-emerald-400',
                    pnl < 0 && 'text-destructive'
                  )}
                >
                  {money(t.pnl)}
                </TableCell>
                <TableCell className="text-right">{percent(t.returnPct, true)}</TableCell>
                <TableCell className="text-right">{money(t.fees)}</TableCell>
                <TableCell className="text-right">{money(t.slippage)}</TableCell>
                <TableCell className="text-right">{duration(t.holdingSeconds)}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>

      <div className="flex items-center justify-end gap-3 text-sm text-muted-foreground">
        <span>
          {offset + 1}–{last} of {data.total}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - PAGE))}
        >
          Previous
        </Button>
        <Button variant="outline" size="sm" disabled={last >= data.total} onClick={() => setOffset(offset + PAGE)}>
          Next
        </Button>
      </div>
    </div>
  );
}
