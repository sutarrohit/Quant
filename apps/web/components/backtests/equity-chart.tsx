'use client';

import type { EquityPoint } from '@quant/contracts/backtest';
import { Area, AreaChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts';

import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from '@/components/ui/chart';
import { money, percent, utcDate, utcDateTime } from '@/lib/format';

const config = {
  equity: { label: 'Realized equity', color: 'var(--primary)' },
  drawdown: { label: 'Drawdown', color: 'var(--destructive)' },
} satisfies ChartConfig;

const tick = (iso: string) => utcDate(iso).replace(/ \d{4}$/, ''); // "1 Jan" -- the year is in the header.

/**
 * Realized equity and its drawdown. Steps, not a line: the value only moves when a
 * trade closes, and a sloped line would invent prices between exits.
 */
export function EquityChart({ points, quote }: { points: EquityPoint[]; quote: string }) {
  const data = points.map((p) => ({ time: p.time, equity: Number(p.equity), drawdown: Number(p.drawdown) }));

  return (
    <div className="flex flex-col gap-2">
      <ChartContainer config={config} className="aspect-auto h-64 w-full">
        <LineChart data={data} margin={{ left: 8, right: 8, top: 8 }} syncId="equity">
          <CartesianGrid vertical={false} />
          <XAxis dataKey="time" tickFormatter={tick} tickLine={false} axisLine={false} minTickGap={48} />
          <YAxis
            domain={['auto', 'auto']}
            tickFormatter={(v: number) => money(v, 0)}
            tickLine={false}
            axisLine={false}
            width={64}
          />
          <ChartTooltip
            content={
              <ChartTooltipContent
                labelFormatter={(_, payload) => utcDateTime(String(payload?.[0]?.payload?.time ?? ''))}
                formatter={(value) => `${money(Number(value))} ${quote}`}
              />
            }
          />
          <Line dataKey="equity" type="stepAfter" stroke="var(--color-equity)" strokeWidth={2} dot={false} />
        </LineChart>
      </ChartContainer>

      <ChartContainer config={config} className="aspect-auto h-28 w-full">
        <AreaChart data={data} margin={{ left: 8, right: 8 }} syncId="equity">
          <CartesianGrid vertical={false} />
          <XAxis dataKey="time" hide />
          <YAxis
            domain={['dataMin', 0]}
            tickFormatter={(v: number) => `${v.toFixed(0)}%`}
            tickLine={false}
            axisLine={false}
            width={64}
          />
          <ChartTooltip
            content={
              <ChartTooltipContent
                labelFormatter={(_, payload) => utcDateTime(String(payload?.[0]?.payload?.time ?? ''))}
                formatter={(value) => percent(Number(value))}
              />
            }
          />
          <Area
            dataKey="drawdown"
            type="stepAfter"
            stroke="var(--color-drawdown)"
            fill="var(--color-drawdown)"
            fillOpacity={0.15}
          />
        </AreaChart>
      </ChartContainer>
    </div>
  );
}
