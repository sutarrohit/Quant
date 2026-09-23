'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { FeesSchema, TIMEFRAME_AGGREGATION } from '@quant/contracts/backtest';
import { MarketSchema } from '@quant/contracts/spec';
import type { SpecError, StrategyDetail } from '@quant/contracts/strategy';
import { RiErrorWarningLine } from '@remixicon/react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { Choice } from '@/components/strategies/choice';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { InputGroup, InputGroupAddon, InputGroupInput, InputGroupText } from '@/components/ui/input-group';
import { createBacktestMutationOptions } from '@/lib/api/backtests/backtest-queries';
import { ApiError } from '@/utils/api-error';

const bps = FeesSchema.shape.makerBps;
const today = () => new Date().toISOString().slice(0, 10);

const FormSchema = z
  .object({
    versionId: z.uuid(),
    symbol: z.string().min(1),
    start: z.iso.date('Pick a start date'),
    end: z.iso.date('Pick an end date'),
    balance: z
      .string()
      .regex(/^\d+(\.\d+)?$/, 'A positive amount')
      .refine((v) => Number(v) > 0, 'A positive amount'),
    fees: FeesSchema,
    slippageBps: bps,
  })
  .refine((v) => v.end > v.start, { path: ['end'], message: 'Must be after the start' })
  .refine((v) => v.end <= today(), { path: ['end'], message: 'Cannot be in the future' });

type FormValues = z.infer<typeof FormSchema>;

const PRESETS = { '1': '1 month', '3': '3 months', '6': '6 months', '12': '1 year' };

function monthsBefore(end: string, months: number) {
  const d = new Date(`${end}T00:00:00Z`);
  d.setUTCMonth(d.getUTCMonth() - months);
  return d.toISOString().slice(0, 10);
}

const marketOf = (spec: unknown) => MarketSchema.safeParse((spec as { market?: unknown } | null)?.market).data;
const quoteOf = (symbol: string) => symbol.split('/')[1] ?? 'USDT';

/** Where to run a saved version, over which window, at what cost. Costs have no zero default. */
export function BacktestForm({ strategy, versionId }: { strategy: StrategyDetail; versionId?: string }) {
  const router = useRouter();
  const client = useQueryClient();
  const create = useMutation(createBacktestMutationOptions(client));
  const [specErrors, setSpecErrors] = useState<SpecError[]>([]);

  const head = strategy.versions[0]!;
  const end = today();
  const form = useForm<FormValues>({
    resolver: zodResolver(FormSchema),
    mode: 'onChange',
    defaultValues: {
      versionId: versionId ?? head.id,
      symbol: marketOf(head.spec)?.symbols[0] ?? '',
      start: monthsBefore(end, 3),
      end,
      balance: '10000',
      fees: { makerBps: '10', takerBps: '10' }, // Binance spot's standard 0.10%.
      slippageBps: '5',
    },
  });

  const chosenId = useWatch({ control: form.control, name: 'versionId' });
  const chosen = strategy.versions.find((v) => v.id === chosenId) ?? head;
  const market = marketOf(chosen.spec);
  const symbol = useWatch({ control: form.control, name: 'symbol' });
  const quote = quoteOf(symbol);

  const versions = Object.fromEntries(
    strategy.versions.map((v) => [v.id, `v${v.version}${v.id === head.id ? ' (latest)' : ''}`])
  );
  const symbols = Object.fromEntries((market?.symbols ?? []).map((s) => [s, s]));

  const onSubmit = async (values: FormValues) => {
    if (!market) return;
    setSpecErrors([]);
    const instrumentId = `${values.symbol.replace('/', '').toUpperCase()}.BINANCE`;

    try {
      const run = await create.mutateAsync({
        versionId: values.versionId,
        venue: 'BINANCE',
        instrumentId,
        barType: `${instrumentId}-${TIMEFRAME_AGGREGATION[market.timeframe]}-LAST-EXTERNAL`,
        start: `${values.start}T00:00:00Z`,
        end: `${values.end}T00:00:00Z`,
        startingBalances: [`${values.balance} ${quoteOf(values.symbol)}`],
        fees: values.fees,
        slippageBps: values.slippageBps,
      });
      router.push(`/backtests/${run.id}`);
    } catch (e) {
      if (e instanceof ApiError && e.specErrors.length) {
        setSpecErrors(e.specErrors); // About the strategy, not this form -- listed, with a way to fix it.
        return;
      }
      toast.error(e instanceof Error ? e.message : 'Could not start the run');
    }
  };

  const setPreset = (months: string) => {
    const end = form.getValues('end') || today();
    form.setValue('start', monthsBefore(end, Number(months)), { shouldValidate: true, shouldDirty: true });
  };

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-6">
        {specErrors.length > 0 && (
          <Alert variant="destructive">
            <RiErrorWarningLine />
            <AlertTitle>This version cannot run over this window</AlertTitle>
            <AlertDescription>
              <ul className="list-disc pl-4">
                {specErrors.map((e) => (
                  <li key={`${e.path}-${e.code}`}>
                    <code className="text-xs">{e.path}</code>: {e.message}
                  </li>
                ))}
              </ul>
              <p>
                Widen the window, or{' '}
                <Link href={`/strategies/${strategy.id}`} className="underline underline-offset-2">
                  edit the strategy
                </Link>
                .
              </p>
            </AlertDescription>
          </Alert>
        )}

        <Card>
          <CardHeader>
            <CardTitle>What to run</CardTitle>
            <CardDescription>
              A saved version only.{' '}
              {market ? `Binance spot · ${market.timeframe} bars.` : 'This version has no market.'}
            </CardDescription>
          </CardHeader>
          <CardContent className="grid items-start gap-4 sm:grid-cols-2">
            <FormField
              control={form.control}
              name="versionId"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Version</FormLabel>
                  <Choice
                    label="Version"
                    value={field.value}
                    options={versions}
                    onChange={(v) => {
                      field.onChange(v);
                      const next = marketOf(strategy.versions.find((x) => x.id === v)?.spec);
                      if (next && !next.symbols.includes(form.getValues('symbol'))) {
                        form.setValue('symbol', next.symbols[0] ?? '');
                      }
                    }}
                  />
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="symbol"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Symbol</FormLabel>
                  <Choice label="Symbol" value={field.value} options={symbols} onChange={field.onChange} />
                  <FormDescription>A backtest runs one symbol at a time.</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Window</CardTitle>
            <CardDescription>
              In UTC. Data the engine does not hold yet is downloaded first, so a long window can take a few minutes.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2">
              {Object.entries(PRESETS).map(([months, label]) => (
                <Button key={months} type="button" variant="outline" size="sm" onClick={() => setPreset(months)}>
                  {label}
                </Button>
              ))}
            </div>
            <div className="grid items-start gap-4 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="start"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Start</FormLabel>
                    <FormControl render={<Input type="date" max={today()} {...field} />} />
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="end"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>End</FormLabel>
                    <FormControl render={<Input type="date" max={today()} {...field} />} />
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Capital and costs</CardTitle>
            <CardDescription>
              Costs are required. A backtest with free trading overstates every result. 10 bps = 0.10%.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid items-start gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <FormField
              control={form.control}
              name="balance"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Starting balance</FormLabel>
                  <InputGroup>
                    <FormControl render={<InputGroupInput inputMode="decimal" {...field} />} />
                    <InputGroupAddon align="inline-end">
                      <InputGroupText>{quote}</InputGroupText>
                    </InputGroupAddon>
                  </InputGroup>
                  <FormMessage />
                </FormItem>
              )}
            />
            {(
              [
                ['fees.makerBps', 'Maker fee'],
                ['fees.takerBps', 'Taker fee'],
                ['slippageBps', 'Slippage'],
              ] as const
            ).map(([name, label]) => (
              <FormField
                key={name}
                control={form.control}
                name={name}
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{label}</FormLabel>
                    <InputGroup>
                      <FormControl render={<InputGroupInput inputMode="decimal" {...field} />} />
                      <InputGroupAddon align="inline-end">
                        <InputGroupText>bps</InputGroupText>
                      </InputGroupAddon>
                    </InputGroup>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ))}
          </CardContent>
        </Card>

        <div className="sticky bottom-0 -mx-6 flex items-center justify-end gap-3 border-t bg-background/95 px-6 py-3 backdrop-blur">
          {!market && <span className="text-sm text-muted-foreground">This version has no market to run.</span>}
          <Button type="submit" disabled={!market || form.formState.isSubmitting}>
            {form.formState.isSubmitting ? 'Starting…' : 'Run backtest'}
          </Button>
        </div>
      </form>
    </Form>
  );
}
