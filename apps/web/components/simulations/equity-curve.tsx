'use client';

import type { SimulationEquity } from '@quant/contracts/simulation';
import { CartesianGrid, Line, LineChart, ReferenceLine, XAxis, YAxis } from 'recharts';

import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from '@/components/ui/chart';
import { money, utcDateTime } from '@/lib/format';

const config = { equity: { label: 'Equity', color: 'var(--primary)' } } satisfies ChartConfig;

const tick = (iso: string) =>
  new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });

/**
 * Equity marked to the close of every bar. A line, unlike a backtest's steps: the
 * open position is revalued each bar, so the value really does move between trades.
 */
export function EquityCurve({
  points,
  baseline,
  quote,
}: {
  points: SimulationEquity['points'];
  baseline: number | null;
  quote: string;
}) {
  const data = points.map((p) => ({ time: p.time, equity: Number(p.equity) }));

  return (
    <ChartContainer config={config} className="aspect-auto h-64 w-full">
      <LineChart data={data} margin={{ left: 8, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="time" tickFormatter={tick} tickLine={false} axisLine={false} minTickGap={64} />
        <YAxis
          domain={['auto', 'auto']}
          tickFormatter={(v: number) => money(v, 0)}
          tickLine={false}
          axisLine={false}
          width={64}
        />
        {baseline !== null && <ReferenceLine y={baseline} stroke="var(--muted-foreground)" strokeDasharray="4 4" />}
        <ChartTooltip
          content={
            <ChartTooltipContent
              labelFormatter={(_, payload) => `${utcDateTime(String(payload?.[0]?.payload?.time ?? ''))} UTC`}
              formatter={(value) => `${money(Number(value))} ${quote}`}
            />
          }
        />
        <Line dataKey="equity" type="linear" stroke="var(--color-equity)" strokeWidth={2} dot={data.length < 3} />
      </LineChart>
    </ChartContainer>
  );
}
