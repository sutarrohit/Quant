'use client';

import { RiCheckboxCircleLine, RiErrorWarningLine } from '@remixicon/react';

import { Button } from '@/components/ui/button';

/** The save bar: why saving is blocked, or the button. */
export function FormFooter({
  runnable,
  submitting,
  blockedReason,
  label,
}: {
  runnable: boolean;
  submitting: boolean;
  blockedReason?: string; // A page-level reason, e.g. a missing name.
  label: string;
}) {
  const reason = blockedReason ?? (runnable ? undefined : 'Fix the highlighted problems to save.');

  return (
    <div className="bg-background/80 sticky bottom-4 z-10 flex items-center justify-end gap-3 rounded-2xl border px-4 py-3 shadow-lg backdrop-blur">
      {reason ? (
        <span className="text-muted-foreground flex items-center gap-1.5 text-sm">
          <RiErrorWarningLine className="size-4 text-amber-500" /> {reason}
        </span>
      ) : (
        <span className="flex items-center gap-1.5 text-sm text-emerald-600 dark:text-emerald-400">
          <RiCheckboxCircleLine className="size-4" /> Ready to save
        </span>
      )}
      <Button type="submit" size="lg" className="px-4" disabled={!!reason || submitting}>
        {submitting ? 'Saving…' : label}
      </Button>
    </div>
  );
}
