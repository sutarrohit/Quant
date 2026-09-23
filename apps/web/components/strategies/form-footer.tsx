'use client';

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
    <div className="sticky bottom-0 -mx-6 flex items-center justify-end gap-3 border-t bg-background/95 px-6 py-3 backdrop-blur">
      {reason && <span className="text-sm text-muted-foreground">{reason}</span>}
      <Button type="submit" disabled={!!reason || submitting}>
        {submitting ? 'Saving…' : label}
      </Button>
    </div>
  );
}
