'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import {
  MAX_LEAVES,
  StrategySpecSchema,
  type ConditionNode,
  type StrategySpec,
  type StrategySpecInput,
} from '@quant/contracts/spec';
import { validateSpec } from '@quant/contracts/spec-validate';
import type { SpecError } from '@quant/contracts/strategy';
import { RiAddLine, RiLoginBoxLine, RiLogoutBoxRLine, RiScales3Line, RiStackLine } from '@remixicon/react';
import { useEffect, type ComponentType, type ReactNode } from 'react';
import { useController, useForm, useWatch, type Control } from 'react-hook-form';

import { SectionTitle } from '@/components/page-header';
import { ConditionNodeEditor } from '@/components/strategies/condition-node';
import { SpecErrorsProvider, buildErrorMap } from '@/components/strategies/spec-errors';
import { SpecPreview } from '@/components/strategies/spec-preview';
import { SymbolsInput } from '@/components/strategies/symbols-input';
import { Choice } from '@/components/strategies/choice';
import { JsonEditorDialog } from '@/components/strategies/json-editor-dialog';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { childrenOf, groupKind, newLeaf } from '@/lib/strategies/tree';
import { useStrategyBuilderStore } from '@/stores/strategy-builder';

const TIMEFRAMES = {
  '1m': '1 minute',
  '5m': '5 minutes',
  '15m': '15 minutes',
  '1h': '1 hour',
  '4h': '4 hours',
  '1d': '1 day',
};

export interface FormStatus {
  runnable: boolean; // Parses and passes every semantic rule.
  submitting: boolean;
}

interface Props {
  defaultValues: StrategySpecInput;
  storeKey: string; // Draft and collapse state are kept under this.
  serverErrors: SpecError[]; // From a rejected save; the same codes as the live check.
  onEdit: () => void; // Clears serverErrors, which describe the spec as it was.
  onSubmit: (spec: StrategySpec) => Promise<unknown>;
  header?: ReactNode;
  footer: (status: FormStatus) => ReactNode;
}

// On a spec that does not parse yet, the rules still see the right shape -- the form only
// ever builds valid shapes -- so run them anyway rather than hide every semantic problem
// behind one bad number. `runnable` still requires a clean parse.
function checkRules(spec: StrategySpecInput | StrategySpec) {
  try {
    return validateSpec(spec as StrategySpec);
  } catch {
    return [];
  }
}

const countLeaves = (n: ConditionNode): number =>
  groupKind(n) ? childrenOf(n).reduce((sum, c) => sum + countLeaves(c), 0) : 1;

export function StrategyForm({ defaultValues, storeKey, serverErrors, onEdit, onSubmit, header, footer }: Props) {
  const form = useForm<StrategySpecInput, unknown, StrategySpec>({
    resolver: zodResolver(StrategySpecSchema),
    defaultValues,
    mode: 'onChange',
  });
  const saveDraft = useStrategyBuilderStore((s) => s.saveDraft);
  const previewOpen = useStrategyBuilderStore((s) => s.previewOpen);

  // Every user edit is kept as a draft, so leaving the page loses nothing.
  useEffect(
    () =>
      form.subscribe({
        formState: { values: true },
        callback: ({ values, type }) => {
          if (type !== 'change') return; // A reset or a programmatic set is not an edit.
          saveDraft(storeKey, values);
          onEdit();
        },
      }),
    [form, saveDraft, storeKey, onEdit]
  );

  // The live check: the same parse and the same rules the server runs.
  const values = useWatch({ control: form.control }) as StrategySpecInput;
  const parsed = StrategySpecSchema.safeParse(values);
  const semantic = checkRules(parsed.success ? parsed.data : values);
  const treeIssues = parsed.success
    ? []
    : parsed.error.issues
        .filter((i) => i.code === 'custom' && i.path.length === 1)
        .map((i) => ({ path: String(i.path[0]), message: i.message }));
  const errorMap = buildErrorMap([...semantic, ...treeIssues, ...serverErrors]);
  const runnable = parsed.success && semantic.length === 0;

  // A pasted spec replaces the form. reset() is not a user edit, so the draft is kept by hand.
  const applyJson = (spec: StrategySpecInput) => {
    form.reset(spec, { keepDefaultValues: true });
    saveDraft(storeKey, spec);
    onEdit();
  };

  return (
    <Form {...form}>
      <SpecErrorsProvider value={errorMap}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-6">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="min-w-0 flex-1">{header}</div>
            <JsonEditorDialog value={values} onApply={applyJson} />
          </div>
          <div
            className={
              previewOpen ? 'grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem] 2xl:grid-cols-[minmax(0,1fr)_28rem]' : ''
            }
          >
            <div className="flex min-w-0 flex-col gap-6">
              <Card>
                <CardHeader>
                  <CardTitle>
                    <SectionTitle icon={RiStackLine} tone="cyan">
                      Market
                    </SectionTitle>
                  </CardTitle>
                  <CardDescription>Binance · Spot — the only venue the engine trades today.</CardDescription>
                </CardHeader>
                <CardContent className="grid items-start gap-4 sm:grid-cols-2">
                  <FormField
                    control={form.control}
                    name="market.symbols"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Symbols</FormLabel>
                        <FormControl render={<SymbolsInput value={field.value} onChange={field.onChange} />} />
                        <FormDescription>Up to 8, comma-separated.</FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="market.timeframe"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Timeframe</FormLabel>
                        <Choice label="Timeframe" value={field.value} options={TIMEFRAMES} onChange={field.onChange} />
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </CardContent>
              </Card>

              <TreeCard
                control={form.control}
                name="entry"
                title="Entry"
                description="When to open a position. Evaluated at each bar's close."
                icon={RiLoginBoxLine}
                tone="emerald"
                storeKey={storeKey}
              />
              <TreeCard
                control={form.control}
                name="exit"
                title="Exit"
                description="When to close it. Risk sizing needs a stop loss in here."
                icon={RiLogoutBoxRLine}
                tone="red"
                storeKey={storeKey}
              />

              <Card>
                <CardHeader>
                  <CardTitle>
                    <SectionTitle icon={RiScales3Line} tone="amber">
                      Sizing
                    </SectionTitle>
                  </CardTitle>
                  <CardDescription>Position size = equity × risk ÷ distance to the stop.</CardDescription>
                </CardHeader>
                <CardContent>
                  <FormField
                    control={form.control}
                    name="sizing.riskPercent"
                    render={({ field }) => (
                      <FormItem className="max-w-48">
                        <FormLabel>Risk per trade (%)</FormLabel>
                        <FormControl
                          render={<Input inputMode="decimal" {...field} value={String(field.value ?? '')} />}
                        />
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </CardContent>
              </Card>
            </div>

            {previewOpen && <SpecPreview spec={parsed.success ? parsed.data : values} valid={runnable} />}
          </div>
          {footer({ runnable, submitting: form.formState.isSubmitting })}
        </form>
      </SpecErrorsProvider>
    </Form>
  );
}

function TreeCard({
  control,
  name,
  title,
  description,
  storeKey,
  icon,
  tone,
}: {
  control: Control<StrategySpecInput, unknown, StrategySpec>;
  name: 'entry' | 'exit';
  title: string;
  description: string;
  storeKey: string;
  icon: ComponentType<{ className?: string }>;
  tone: 'emerald' | 'red';
}) {
  const { field } = useController({ control, name });
  const root = field.value as ConditionNode;
  const isGroup = groupKind(root) !== null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <SectionTitle icon={icon} tone={tone}>
            {title}
          </SectionTitle>
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <ConditionNodeEditor
          node={root}
          path={name}
          level={1}
          allowExit={name === 'exit'}
          atLeafLimit={countLeaves(root) >= MAX_LEAVES}
          storeKey={storeKey}
          onChange={field.onChange}
        />
        {!isGroup && (
          <button
            type="button"
            className="text-muted-foreground flex items-center justify-center gap-1.5 rounded-xl border border-dashed py-2.5 text-xs transition-colors hover:border-emerald-500/50 hover:text-emerald-600 dark:hover:text-emerald-400"
            onClick={() => field.onChange({ all: [root, newLeaf()] })}
          >
            <RiAddLine className="size-3.5" /> Combine with another condition
          </button>
        )}
      </CardContent>
    </Card>
  );
}
