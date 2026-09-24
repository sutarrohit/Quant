'use client';

import { RiCheckboxCircleLine, RiCodeSSlashLine, RiErrorWarningLine } from '@remixicon/react';

import { SectionTitle } from '@/components/page-header';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

/** The spec exactly as it will be saved and sent to the engine. */
export function SpecPreview({ spec, valid }: { spec: unknown; valid: boolean }) {
  return (
    <Card className="h-fit lg:sticky lg:top-4">
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="text-sm">
          <SectionTitle icon={RiCodeSSlashLine} tone="violet">
            JSON
          </SectionTitle>
        </CardTitle>
        <span
          className={cn(
            'flex items-center gap-1 rounded-full px-2 py-0.5 text-xs',
            valid
              ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
              : 'bg-red-500/10 text-red-600 dark:text-red-400'
          )}
        >
          {valid ? <RiCheckboxCircleLine className="size-4" /> : <RiErrorWarningLine className="size-4" />}
          {valid ? 'Runnable' : 'Not runnable yet'}
        </span>
      </CardHeader>
      <CardContent>
        <pre
          tabIndex={0} // Scrollable, so it must be reachable by keyboard.
          aria-label="Strategy JSON"
          className="max-h-[70vh] overflow-auto rounded-xl border bg-zinc-950 p-4 text-xs leading-relaxed text-zinc-300"
        >
          {JSON.stringify(spec, null, 2)}
        </pre>
      </CardContent>
    </Card>
  );
}
