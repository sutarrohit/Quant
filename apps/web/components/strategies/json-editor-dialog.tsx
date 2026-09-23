'use client';

import { StrategySpecSchema, type StrategySpecInput } from '@quant/contracts/spec';
import { validateSpec } from '@quant/contracts/spec-validate';
import { RiBracesLine, RiCheckboxCircleLine, RiErrorWarningLine, RiFileCopyLine } from '@remixicon/react';
import { useState } from 'react';
import type { z } from 'zod';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';

type Check =
  | { kind: 'syntax'; message: string }
  | { kind: 'schema'; problems: string[] }
  | { kind: 'ok'; spec: StrategySpecInput; warnings: string[] };

type Issue = z.core.$ZodIssue;

// A branch missing its own keys is not the one the user meant, so missing keys weigh most.
// Nested unions count as their closest branch; one with no branch matched its discriminator.
const MISSING = 10;
const distance = (issues: Issue[]): number =>
  issues.reduce((sum, i) => {
    if (i.code === 'invalid_union') {
      return sum + (i.errors.length ? 1 + Math.min(...i.errors.map(distance)) : MISSING);
    }
    return sum + (/received undefined$/.test(i.message) ? MISSING : 1);
  }, 0);

/**
 * "entry: Invalid input" says nothing when no condition shape matched. For a union,
 * report the branch that came closest with its full path instead.
 */
function describe(issue: Issue, prefix: PropertyKey[]): string[] {
  const path = [...prefix, ...issue.path];
  if (issue.code === 'invalid_union' && issue.errors.length > 0) {
    const closest = issue.errors.reduce((a, b) => (distance(b) < distance(a) ? b : a));
    if (closest.length > 0) return closest.flatMap((i) => describe(i, path));
  }
  return [`${path.map(String).join('.') || 'spec'}: ${issue.message}`];
}

/**
 * Parse, then schema, then rules. Only the first two block Apply: the builder can show
 * a rule break against the right field, but it cannot render a shape it does not know.
 */
function check(text: string, identity: Pick<StrategySpecInput, 'strategyId' | 'version'>): Check {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (e) {
    return { kind: 'syntax', message: e instanceof Error ? e.message : 'Not valid JSON' };
  }
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    return { kind: 'syntax', message: 'Expected a JSON object: { "market": …, "entry": …, … }' };
  }

  const parsed = StrategySpecSchema.safeParse({ ...raw, ...identity }); // Identity is the strategy's, not the paste's.
  if (!parsed.success) {
    return { kind: 'schema', problems: parsed.error.issues.flatMap((i) => describe(i, [])) };
  }

  const warnings = validateSpec(parsed.data).map((e) => `${e.path}: ${e.message}`);
  return { kind: 'ok', spec: parsed.data, warnings };
}

/** Paste or hand-edit the whole spec. Apply replaces the builder's contents; saving is still the builder's job. */
export function JsonEditorDialog({
  value,
  onApply,
}: {
  value: StrategySpecInput;
  onApply: (spec: StrategySpecInput) => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const identity = { strategyId: value.strategyId, version: value.version };
  const result = check(text, identity);

  const openWith = (next: boolean) => {
    if (next) setText(JSON.stringify(value, null, 2)); // Start from what the builder holds now.
    setOpen(next);
  };

  const format = () => {
    try {
      setText(JSON.stringify(JSON.parse(text), null, 2));
    } catch {
      /* Leave it; the syntax error is already shown. */
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success('Copied');
    } catch {
      toast.error('Could not copy');
    }
  };

  const apply = () => {
    if (result.kind !== 'ok') return;
    onApply(result.spec);
    setOpen(false);
    toast.success(result.warnings.length ? 'Applied. Fix the highlighted problems to save.' : 'Applied');
  };

  return (
    <Dialog open={open} onOpenChange={openWith}>
      <Button type="button" variant="outline" size="sm" onClick={() => openWith(true)}>
        <RiBracesLine /> Edit as JSON
      </Button>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Edit as JSON</DialogTitle>
          <DialogDescription>
            Paste a whole spec or edit this one. Apply replaces the builder; nothing is saved until you save.{' '}
            <code className="text-xs">strategyId</code> and <code className="text-xs">version</code> are kept from this
            strategy.
          </DialogDescription>
        </DialogHeader>

        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          spellCheck={false}
          aria-label="Strategy JSON"
          aria-invalid={result.kind !== 'ok' || undefined}
          className="h-[50vh] resize-none font-mono text-xs leading-relaxed"
        />

        <div className="max-h-32 overflow-auto text-sm" aria-live="polite">
          {result.kind === 'syntax' && (
            <p className="flex items-start gap-1.5 text-destructive">
              <RiErrorWarningLine className="mt-0.5 size-4 shrink-0" /> {result.message}
            </p>
          )}
          {result.kind === 'schema' && (
            <div className="flex flex-col gap-1 text-destructive">
              <p className="flex items-center gap-1.5 font-medium">
                <RiErrorWarningLine className="size-4" /> The builder cannot show this spec:
              </p>
              <ul className="list-disc pl-6 text-xs">
                {result.problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </div>
          )}
          {result.kind === 'ok' && result.warnings.length === 0 && (
            <p className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400">
              <RiCheckboxCircleLine className="size-4" /> Valid and runnable.
            </p>
          )}
          {result.kind === 'ok' && result.warnings.length > 0 && (
            <div className="flex flex-col gap-1 text-amber-600 dark:text-amber-400">
              <p className="flex items-center gap-1.5 font-medium">
                <RiErrorWarningLine className="size-4" /> Can be applied, but must be fixed before saving:
              </p>
              <ul className="list-disc pl-6 text-xs">
                {result.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <DialogFooter className="sm:justify-between">
          <div className="flex gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={format} disabled={result.kind === 'syntax'}>
              Format
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => void copy()}>
              <RiFileCopyLine /> Copy
            </Button>
          </div>
          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="button" onClick={apply} disabled={result.kind !== 'ok'}>
              Apply
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
