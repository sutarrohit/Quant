import type { ReactNode } from 'react';

/** A label and its value, one line of a card. */
export function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="border-border/60 flex items-baseline justify-between gap-4 border-b py-2.5 text-sm last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right tabular-nums">{children}</span>
    </div>
  );
}
