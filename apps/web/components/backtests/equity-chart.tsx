'use client';

import type { EquityPoint } from '@quant/contracts/backtest';
import { useId } from 'react';
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from 'recharts';

import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from '@/components/ui/chart';
import { money, percent, utcDate, utcDateTime } from '@/lib/format';

const UP = 'rgb(16 185 129)';
const DOWN = 'rgb(239 68 68)';

const tick = (iso: string) => utcDate(iso).replace(/ \d{4}$/, ''); // "1 Jan" -- the year is in the header.

/**
 * Realized equity and its drawdown. Steps, not a line: the value only moves when a
 * trade closes, and a sloped line would invent prices between exits.
 */
export function EquityChart({ points, quote }: { points: EquityPoint[]; quote: string }) {
  const id = useId().replaceAll(':', '');
  const data = points.map((p) => ({ time: p.time, equity: Number(p.equity), drawdown: Number(p.drawdown) }));
  const up = (data.at(-1)?.equity ?? 0) >= (data[0]?.equity ?? 0);
  const config = {
    equity: { label: 'Realized equity', color: up ? UP : DOWN },
    drawdown: { label: 'Drawdown', color: DOWN },
  } satisfies ChartConfig;

  return (
    <div className="flex flex-col gap-2">
      <ChartContainer config={config} className="aspect-auto h-72 w-full">
        <AreaChart data={data} margin={{ left: 8, right: 8, top: 8 }} syncId="equity">
          <defs>
            <linearGradient id={`${id}-equity`} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="var(--color-equity)" stopOpacity={0.35} />
              <stop offset="100%" stopColor="var(--color-equity)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
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
          <Area
            dataKey="equity"
            type="stepAfter"
            stroke="var(--color-equity)"
            strokeWidth={2}
            fill={`url(#${id}-equity)`}
            baseValue="dataMin"
          />
        </AreaChart>
      </ChartContainer>

      <ChartContainer config={config} className="aspect-auto h-28 w-full">
        <AreaChart data={data} margin={{ left: 8, right: 8 }} syncId="equity">
          <defs>
            <linearGradient id={`${id}-dd`} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="var(--color-drawdown)" stopOpacity={0} />
              <stop offset="100%" stopColor="var(--color-drawdown)" stopOpacity={0.35} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
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
            strokeWidth={1.5}
            fill={`url(#${id}-dd)`}
          />
        </AreaChart>
      </ChartContainer>
    </div>
  );
}
