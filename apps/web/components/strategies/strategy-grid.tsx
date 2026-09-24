'use client';

import type { Strategy } from '@quant/contracts/strategy';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { toast } from 'sonner';

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
import { CardGrid } from '@/components/metric-card';
import { StrategyCard } from '@/components/strategies/strategy-card';
import { archiveStrategyMutationOptions } from '@/lib/api/strategies/strategy-queries';
import { toastError } from '@/utils/toast-error';

export function StrategyGrid({ strategies }: { strategies: Strategy[] }) {
  const client = useQueryClient();
  const [archiving, setArchiving] = useState<Strategy | null>(null);

  const archive = useMutation({
    ...archiveStrategyMutationOptions(client),
    onSuccess: (...args) => {
      archiveStrategyMutationOptions(client).onSuccess?.(...args);
      toast.success(`Archived “${archiving?.name}”`);
      setArchiving(null);
    },
    onError: (error) => toastError(error),
  });

  return (
    <>
      <CardGrid>
        {strategies.map((strategy) => (
          <StrategyCard key={strategy.id} strategy={strategy} onArchive={() => setArchiving(strategy)} />
        ))}
      </CardGrid>

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
