'use client';

import type { StrategyVersion } from '@quant/contracts/strategy';
import { RiHistoryLine } from '@remixicon/react';
import { useState } from 'react';

import { SectionTitle } from '@/components/page-header';
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
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
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
    <Card>
      <CardHeader>
        <CardTitle>
          <SectionTitle icon={RiHistoryLine} tone="violet">
            Versions
          </SectionTitle>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {/* A timeline: newest on top, a rail joining the dots. */}
        <ol className="relative flex flex-col">
          <span aria-hidden className="bg-border absolute top-3 bottom-3 left-[11px] w-px" />
          {versions.map((v) => {
            const selected = v.version === current;
            return (
              <li key={v.id}>
                <button
                  type="button"
                  onClick={() => choose(v.version)}
                  aria-current={selected || undefined}
                  className={cn(
                    'group relative flex w-full items-center gap-3 rounded-lg py-1.5 pr-2 text-left text-sm transition-colors',
                    selected ? 'font-semibold' : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  <span
                    className={cn(
                      'relative flex size-6 shrink-0 items-center justify-center rounded-full border text-[10px]',
                      selected
                        ? 'border-emerald-500 bg-emerald-500 text-black'
                        : 'bg-card group-hover:border-foreground/40'
                    )}
                  >
                    {v.version}
                  </span>
                  <span className="flex flex-1 items-center gap-2">
                    v{v.version}
                    {v.version === head && (
                      <span className="rounded-full bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
                        latest
                      </span>
                    )}
                  </span>
                  <span className="text-muted-foreground text-xs font-normal" title={v.createdAt}>
                    {timeAgo(v.createdAt)}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </CardContent>

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
    </Card>
  );
}
