'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { FeesSchema, TIMEFRAME_AGGREGATION } from '@quant/contracts/backtest';
import { RiskLimitsSchema } from '@quant/contracts/simulation';
import { MarketSchema } from '@quant/contracts/spec';
import type { StrategyDetail } from '@quant/contracts/strategy';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useForm, useWatch } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { Choice } from '@/components/strategies/choice';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { InputGroup, InputGroupAddon, InputGroupInput, InputGroupText } from '@/components/ui/input-group';
import { createSimulationMutationOptions } from '@/lib/api/simulations/simulation-queries';

const blankable = <T extends z.ZodType>(schema: T) => z.union([z.literal(''), schema]); // Blank means unlimited.
const limits = RiskLimitsSchema.shape;

const FormSchema = z.object({
  name: z.string().trim().min(1, 'Give it a name').max(200),
  versionId: z.uuid(),
  symbol: z.string().min(1),
  fees: FeesSchema,
  slippageBps: FeesSchema.shape.makerBps,
  risk: z.object({
    maxOrderNotional: blankable(limits.maxOrderNotional.unwrap()),
    maxPositionNotional: blankable(limits.maxPositionNotional.unwrap()),
    maxOpenPositions: blankable(z.string().regex(/^[1-9]\d*$/, 'A whole number, 1 or more')),
    dailyLossLimit: blankable(limits.dailyLossLimit.unwrap()),
  }),
});

type FormValues = z.infer<typeof FormSchema>;

const marketOf = (spec: unknown) => MarketSchema.safeParse((spec as { market?: unknown } | null)?.market).data;
const quoteOf = (symbol: string) => symbol.split('/')[1] ?? 'USDT';

/** Paper-trade a saved version. The account and its id are the server's to mint. */
export function SimulationForm({ strategy, versionId }: { strategy: StrategyDetail; versionId?: string }) {
  const router = useRouter();
  const client = useQueryClient();
  const create = useMutation(createSimulationMutationOptions(client));
  const head = strategy.versions[0]!;

  const form = useForm<FormValues>({
    resolver: zodResolver(FormSchema),
    mode: 'onChange',
    defaultValues: {
      name: `${strategy.name} (paper)`,
      versionId: versionId ?? head.id,
      symbol: marketOf(head.spec)?.symbols[0] ?? '',
      fees: { makerBps: '10', takerBps: '10' }, // Binance spot's standard 0.10%.
      slippageBps: '5',
      risk: { maxOrderNotional: '', maxPositionNotional: '', maxOpenPositions: '', dailyLossLimit: '' },
    },
  });

  const chosenId = useWatch({ control: form.control, name: 'versionId' });
  const market = marketOf((strategy.versions.find((v) => v.id === chosenId) ?? head).spec);
  const quote = quoteOf(useWatch({ control: form.control, name: 'symbol' }));

  const versions = Object.fromEntries(
    strategy.versions.map((v) => [v.id, `v${v.version}${v.id === head.id ? ' (latest)' : ''}`])
  );
  const symbols = Object.fromEntries((market?.symbols ?? []).map((s) => [s, s]));

  const onSubmit = async (values: FormValues) => {
    if (!market) return;
    const instrumentId = `${values.symbol.replace('/', '').toUpperCase()}.BINANCE`;
    const r = values.risk;
    const risk = {
      ...(r.maxOrderNotional && { maxOrderNotional: r.maxOrderNotional }),
      ...(r.maxPositionNotional && { maxPositionNotional: r.maxPositionNotional }),
      ...(r.maxOpenPositions && { maxOpenPositions: Number(r.maxOpenPositions) }),
      ...(r.dailyLossLimit && { dailyLossLimit: r.dailyLossLimit }),
    };

    try {
      const sim = await create.mutateAsync({
        name: values.name,
        versionId: values.versionId,
        venue: 'BINANCE',
        instrumentId,
        barType: `${instrumentId}-${TIMEFRAME_AGGREGATION[market.timeframe]}-LAST-EXTERNAL`,
        fees: values.fees,
        slippageBps: values.slippageBps,
        ...(Object.keys(risk).length > 0 && { risk }),
      });
      router.push(`/simulations/${sim.id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not start the simulation');
    }
  };

  const unit = (text: string) => (
    <InputGroupAddon align="inline-end">
      <InputGroupText>{text}</InputGroupText>
    </InputGroupAddon>
  );

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-6">
        <Card>
          <CardHeader>
            <CardTitle>What to run</CardTitle>
            <CardDescription>
              Live market data, simulated fills, no real money. A paper account starts with 10,000 USDT.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid items-start gap-4 sm:grid-cols-3">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl render={<Input maxLength={200} {...field} />} />
                  <FormMessage />
                </FormItem>
              )}
            />
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
                  <FormDescription>
                    {market ? `${market.timeframe} bars` : 'This version has no market.'}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Costs</CardTitle>
            <CardDescription>
              Required, like a backtest. The exchange&apos;s public data reports zero fees, so they are declared here.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid items-start gap-4 sm:grid-cols-3">
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
                      {unit('bps')}
                    </InputGroup>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Risk limits</CardTitle>
            <CardDescription>For the whole account. Leave a field blank for no limit.</CardDescription>
          </CardHeader>
          <CardContent className="grid items-start gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {(
              [
                ['risk.maxOrderNotional', 'Max order size', quote],
                ['risk.maxPositionNotional', 'Max position size', quote],
                ['risk.dailyLossLimit', 'Daily loss limit', quote],
                ['risk.maxOpenPositions', 'Max open positions', ''],
              ] as const
            ).map(([name, label, suffix]) => (
              <FormField
                key={name}
                control={form.control}
                name={name}
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{label}</FormLabel>
                    <InputGroup>
                      <FormControl render={<InputGroupInput inputMode="decimal" placeholder="No limit" {...field} />} />
                      {suffix && unit(suffix)}
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
            {form.formState.isSubmitting ? 'Starting…' : 'Start paper trading'}
          </Button>
        </div>
      </form>
    </Form>
  );
}
