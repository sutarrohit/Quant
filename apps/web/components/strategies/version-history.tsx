'use client';

import type { StrategyVersion } from '@quant/contracts/strategy';
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
import { Badge } from '@/components/ui/badge';
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
        <CardTitle className="text-sm">Versions</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-1 p-2">
        {versions.map((v) => (
          <button
            key={v.id}
            type="button"
            onClick={() => choose(v.version)}
            className={cn(
              'flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted',
              v.version === current && 'bg-muted font-medium'
            )}
          >
            <span className="flex items-center gap-2">
              v{v.version}
              {v.version === head && <Badge variant="secondary">latest</Badge>}
            </span>
            <span
              className={cn('text-xs', v.version === current ? 'text-foreground/80' : 'text-muted-foreground')}
              title={v.createdAt}
            >
              {timeAgo(v.createdAt)}
            </span>
          </button>
        ))}
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
