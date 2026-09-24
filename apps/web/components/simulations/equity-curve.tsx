'use client';

import type { SimulationEquity } from '@quant/contracts/simulation';
import { useId } from 'react';
import { Area, AreaChart, CartesianGrid, ReferenceLine, XAxis, YAxis } from 'recharts';

import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from '@/components/ui/chart';
import { barClose } from '@/lib/bars';
import { money, utcDateTime } from '@/lib/format';

const tick = (iso: string) =>
  new Date(iso).toLocaleString('en-GB', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
  });

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
  const id = useId().replaceAll(':', '');
  const data = points.map((p) => ({ time: barClose(p.time), equity: Number(p.equity) }));
  // Green above the starting balance, red below it.
  const last = data.at(-1)?.equity ?? 0;
  const up = last >= (baseline ?? data[0]?.equity ?? last);
  const config = {
    equity: { label: 'Equity', color: up ? 'rgb(16 185 129)' : 'rgb(239 68 68)' },
  } satisfies ChartConfig;

  return (
    <ChartContainer config={config} className="aspect-auto h-72 w-full">
      <AreaChart data={data} margin={{ left: 8, right: 8, top: 8 }}>
        <defs>
          <linearGradient id={`${id}-equity`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--color-equity)" stopOpacity={0.35} />
            <stop offset="100%" stopColor="var(--color-equity)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} strokeDasharray="3 3" />
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
        <Area
          dataKey="equity"
          type="linear"
          stroke="var(--color-equity)"
          strokeWidth={2}
          fill={`url(#${id}-equity)`}
          baseValue="dataMin"
          dot={data.length < 3}
        />
      </AreaChart>
    </ChartContainer>
  );
}
