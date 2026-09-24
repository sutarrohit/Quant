'use client';

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { simulationFillsQueryOptions } from '@/lib/api/simulations/simulation-queries';
import { cn } from '@/lib/utils';
import { money, utcDateTime } from '@/lib/format';

const PAGE = 20;

/** Every fill, from Postgres, so it outlives the engine's capped stream. Newest first. */
export function FillTable({ simulationId }: { simulationId: string }) {
  const [page, setPage] = useState(1);
  const { data, isPending, error, isPlaceholderData } = useQuery(simulationFillsQueryOptions(simulationId, page, PAGE));

  if (isPending) return <Skeleton className="h-32 w-full" />;
  if (error) return <p className="text-sm text-destructive">Could not load fills: {error.message}</p>;
  if (data.pagination.total === 0) return <p className="text-sm text-muted-foreground">No fills yet.</p>;

  const { total, totalPages } = data.pagination;

  return (
    <div className={cn('flex flex-col gap-3', isPlaceholderData && 'opacity-60')}>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Time (UTC)</TableHead>
            <TableHead>Side</TableHead>
            <TableHead className="text-right">Qty</TableHead>
            <TableHead className="text-right">Price</TableHead>
            <TableHead className="text-right">Notional</TableHead>
            <TableHead className="text-right">Fee</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.data.map((f) => (
            <TableRow key={f.tradeId}>
              <TableCell className="tabular-nums">{utcDateTime(f.filledAt)}</TableCell>
              <TableCell
                className={cn(
                  f.side === 'BUY' ? 'text-emerald-700 dark:text-emerald-400' : 'text-red-700 dark:text-destructive'
                )}
              >
                {f.side === 'BUY' ? 'Buy' : 'Sell'}
              </TableCell>
              <TableCell className="text-right tabular-nums">{money(f.quantity, 3)}</TableCell>
              <TableCell className="text-right tabular-nums">{money(f.price)}</TableCell>
              <TableCell className="text-right tabular-nums">{money(Number(f.quantity) * Number(f.price))}</TableCell>
              <TableCell className="text-right tabular-nums">
                {money(f.commission.amount, 4)} {f.commission.currency}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {totalPages > 1 && (
        <div className="flex items-center justify-end gap-3 text-sm text-muted-foreground">
          <span>
            Page {page} of {totalPages} · {total} fills
          </span>
          <Button variant="outline" size="sm" disabled={page === 1} onClick={() => setPage(page - 1)}>
            Newer
          </Button>
          <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>
            Older
          </Button>
        </div>
      )}
    </div>
  );
}
