'use client';

import { MarketSchema } from '@quant/contracts/spec';
import type { Strategy } from '@quant/contracts/strategy';
import { RiMore2Line } from '@remixicon/react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { archiveStrategyMutationOptions } from '@/lib/api/strategies/strategy-queries';
import { timeAgo } from '@/lib/format';

// `spec` is untyped on the wire; parse just the market so an odd stored spec shows "—" rather than crashing.
function marketOf(spec: unknown) {
  const parsed = MarketSchema.safeParse((spec as { market?: unknown } | null)?.market);
  return parsed.success ? parsed.data : null;
}

export function StrategyTable({ strategies }: { strategies: Strategy[] }) {
  const router = useRouter();
  const client = useQueryClient();
  const [archiving, setArchiving] = useState<Strategy | null>(null);

  const archive = useMutation({
    ...archiveStrategyMutationOptions(client),
    onSuccess: (...args) => {
      archiveStrategyMutationOptions(client).onSuccess?.(...args);
      toast.success(`Archived “${archiving?.name}”`);
      setArchiving(null);
    },
    onError: (error) => toast.error(error.message),
  });

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Market</TableHead>
            <TableHead>Version</TableHead>
            <TableHead>Updated</TableHead>
            <TableHead className="w-10" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {strategies.map((strategy) => {
            const market = marketOf(strategy.latestVersion?.spec);
            return (
              <TableRow key={strategy.id}>
                <TableCell className="font-medium">
                  <Link href={`/strategies/${strategy.id}`} className="hover:underline">
                    {strategy.name}
                  </Link>
                </TableCell>
                <TableCell>
                  {market ? (
                    <span className="flex items-center gap-2">
                      {market.symbols.join(', ')}
                      <Badge variant="outline">{market.timeframe}</Badge>
                    </span>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell>{strategy.latestVersion ? `v${strategy.latestVersion.version}` : '—'}</TableCell>
                <TableCell className="text-muted-foreground" title={strategy.updatedAt}>
                  {timeAgo(strategy.updatedAt)}
                </TableCell>
                <TableCell>
                  <DropdownMenu>
                    <DropdownMenuTrigger render={<Button variant="ghost" size="icon" aria-label="Actions" />}>
                      <RiMore2Line />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onClick={() => router.push(`/strategies/${strategy.id}`)}>Open</DropdownMenuItem>
                      <DropdownMenuItem variant="destructive" onClick={() => setArchiving(strategy)}>
                        Archive
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>

      <AlertDialog open={archiving !== null} onOpenChange={(open) => !open && setArchiving(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Archive “{archiving?.name}”?</AlertDialogTitle>
            <AlertDialogDescription>
              It disappears from this list. Its versions stay readable, so any backtest that used one still makes sense.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={archive.isPending}
              onClick={() => archiving && archive.mutate(archiving.id)}
            >
              {archive.isPending ? 'Archiving…' : 'Archive'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
