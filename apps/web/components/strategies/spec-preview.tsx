'use client';

import { RiCheckboxCircleLine, RiErrorWarningLine } from '@remixicon/react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

/** The spec exactly as it will be saved and sent to the engine. */
export function SpecPreview({ spec, valid }: { spec: unknown; valid: boolean }) {
  return (
    <Card className="h-fit lg:sticky lg:top-4">
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="text-sm">JSON</CardTitle>
        <span className={`flex items-center gap-1 text-xs ${valid ? 'text-emerald-600' : 'text-destructive'}`}>
          {valid ? <RiCheckboxCircleLine className="size-4" /> : <RiErrorWarningLine className="size-4" />}
          {valid ? 'Runnable' : 'Not runnable yet'}
        </span>
      </CardHeader>
      <CardContent>
        <pre className="max-h-[70vh] overflow-auto rounded-md bg-muted p-3 text-xs leading-relaxed">
          {JSON.stringify(spec, null, 2)}
        </pre>
      </CardContent>
    </Card>
  );
}
