'use client';

import { useId, type ReactNode } from 'react';

import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

// Shared pieces of the strategy, backtest and simulation cards.

export const CARD_CLASS =
  'group bg-card relative flex flex-col gap-4 rounded-2xl border p-5 transition-all duration-200 hover:-translate-y-0.5 hover:border-emerald-500/40 hover:shadow-lg hover:shadow-emerald-500/5';

export function CardGrid({ children }: { children: ReactNode }) {
  return <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">{children}</div>;
}

export function Sparkline({ values, up }: { values: number[]; up: boolean }) {
  const id = useId();
  const min = Math.min(...values);
  const range = Math.max(...values) - min || 1;
  const step = 100 / Math.max(values.length - 1, 1);
  const line = values
    .map((v, i) => `${i ? 'L' : 'M'}${(i * step).toFixed(2)},${(38 - ((v - min) / range) * 36).toFixed(2)}`)
    .join(' ');
  const color = up ? 'rgb(16 185 129)' : 'rgb(239 68 68)';

  return (
    <svg viewBox="0 0 100 40" preserveAspectRatio="none" className="h-full w-full" aria-hidden>
      <defs>
        <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.3" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${line} L100,40 L0,40 Z`} fill={`url(#${id})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** The chart well: a sparkline once there are 2+ points, otherwise a skeleton or a short note. */
export function ChartWell({
  values,
  up,
  loading,
  empty,
  badge,
  className,
}: {
  values: number[] | undefined;
  up: boolean;
  loading: boolean;
  empty: ReactNode;
  badge?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('bg-muted/40 relative h-20 overflow-hidden rounded-lg', className)}>
      {loading ? (
        <Skeleton className="h-full w-full rounded-none" />
      ) : values && values.length > 1 ? (
        <Sparkline values={values} up={up} />
      ) : (
        <div className="text-muted-foreground flex h-full items-center justify-center px-3 text-center text-xs">
          {empty}
        </div>
      )}
      {badge && <div className="absolute top-2 right-2">{badge}</div>}
    </div>
  );
}

export type Tone = 'up' | 'down' | undefined;

export const toneOf = (value: string | number | null | undefined): Tone =>
  value == null ? undefined : Number(value) > 0 ? 'up' : Number(value) < 0 ? 'down' : undefined;

export function Metric({ label, value, tone }: { label: string; value: string; tone?: Tone }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="text-muted-foreground text-[10px] font-medium tracking-wider uppercase">{label}</span>
      <span
        className={cn(
          'truncate text-base font-semibold tabular-nums',
          tone === 'up' && 'text-emerald-600 dark:text-emerald-400',
          tone === 'down' && 'text-red-600 dark:text-red-400'
        )}
      >
        {value}
      </span>
    </div>
  );
}

export function MetricGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-x-4 gap-y-3">{children}</div>;
}

/** Small pill for a version or tag, in the card header. */
export function Pill({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold tracking-wider text-emerald-600 dark:text-emerald-400">
      {children}
    </span>
  );
}

export function CardSkeleton() {
  return (
    <div className="flex flex-col gap-4 rounded-2xl border p-5">
      <Skeleton className="h-5 w-2/3" />
      <Skeleton className="h-20 w-full" />
      <div className="grid grid-cols-2 gap-3">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-9" />
        ))}
      </div>
      <Skeleton className="h-7 w-full" />
    </div>
  );
}

export function CardGridSkeleton({ count = 4 }: { count?: number }) {
  return (
    <CardGrid>
      {Array.from({ length: count }, (_, i) => (
        <CardSkeleton key={i} />
      ))}
    </CardGrid>
  );
}

/** "SOLUSDT" and "15m" from a Nautilus instrument id and bar type. */
export const symbolOf = (instrumentId: string) => instrumentId.replace(/\.[A-Z]+$/, '');

const UNIT: Record<string, string> = { MINUTE: 'm', HOUR: 'h', DAY: 'd' };
export const shortTimeframe = (barType: string) => {
  const [, step, unit] = barType.split('-'); // e.g. SOLUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL
  return step && unit ? `${step}${UNIT[unit] ?? unit.toLowerCase()}` : barType;
};

/** Overlay badge for the chart well, e.g. "Running". */
export function WellBadge({ children }: { children: ReactNode }) {
  return (
    <span className="bg-background/80 text-muted-foreground flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] backdrop-blur">
      {children}
    </span>
  );
}
