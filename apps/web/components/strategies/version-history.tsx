'use client';

import type { StrategyVersion } from '@quant/contracts/strategy';
import { RiHistoryLine } from '@remixicon/react';
import { useState } from 'react';

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
import { timeAgo } from '@/lib/format';
import { cn } from '@/lib/utils';

/** Every saved version, newest first. Picking one loads it into the form. */
export function VersionHistory({
  versions,
  current,
  hasDraft,
  onSelect,
}: {
  versions: StrategyVersion[];
  current: number;
  hasDraft: boolean; // Switching would drop unsaved edits, so ask first.
  onSelect: (version: number) => void;
}) {
  const [pending, setPending] = useState<number | null>(null);
  const head = versions[0]?.version;

  const choose = (version: number) => {
    if (version === current) return;
    if (hasDraft) setPending(version);
    else onSelect(version);
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-muted-foreground mr-1 flex items-center gap-1.5 text-[10px] font-medium tracking-wider uppercase">
        <RiHistoryLine className="size-3.5" /> Versions
      </span>
      {versions.map((v) => {
        const selected = v.version === current;
        return (
          <button
            key={v.id}
            type="button"
            onClick={() => choose(v.version)}
            aria-current={selected || undefined}
            title={v.createdAt}
            className={cn(
              'flex items-center gap-2 rounded-full border px-3 py-1 text-xs transition-colors',
              selected
                ? 'border-emerald-500/50 bg-emerald-500/10 font-semibold text-emerald-600 dark:text-emerald-400'
                : 'text-muted-foreground hover:border-foreground/30 hover:text-foreground'
            )}
          >
            v{v.version}
            {v.version === head && (
              <span className="rounded-full bg-emerald-500/15 px-1.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
                latest
              </span>
            )}
            <span className="font-normal opacity-70">{timeAgo(v.createdAt)}</span>
          </button>
        );
      })}

      <AlertDialog open={pending !== null} onOpenChange={(open) => !open && setPending(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard unsaved changes?</AlertDialogTitle>
            <AlertDialogDescription>Opening v{pending} replaces what is in the form now.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep editing</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                if (pending !== null) onSelect(pending);
                setPending(null);
              }}
            >
              Discard and open v{pending}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
