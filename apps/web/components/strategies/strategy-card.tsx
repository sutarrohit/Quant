'use client';

import { MarketSchema } from '@quant/contracts/spec';
import { isTerminal } from '@quant/contracts/backtest';
import type { Strategy } from '@quant/contracts/strategy';
import { RiArrowRightLine, RiLoader4Line, RiMore2Line } from '@remixicon/react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { BacktestMetrics } from '@/components/backtests/backtest-card';
import { CARD_CLASS, ChartWell, Pill, WellBadge } from '@/components/metric-card';
import { Button, buttonVariants } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { backtestsQueryOptions, equityQueryOptions } from '@/lib/api/backtests/backtest-queries';
import { timeAgo } from '@/lib/format';

// `spec` is untyped on the wire; parse just the market so an odd stored spec shows "—" rather than crashing.
function marketOf(spec: unknown) {
  const parsed = MarketSchema.safeParse((spec as { market?: unknown } | null)?.market);
  return parsed.success ? parsed.data : null;
}

export function StrategyCard({ strategy, onArchive }: { strategy: Strategy; onArchive: () => void }) {
  const router = useRouter();
  const market = marketOf(strategy.latestVersion?.spec);

  // Newest first, so the first SUCCEEDED run is the latest result.
  const runs = useQuery(backtestsQueryOptions({ strategyId: strategy.id, pageSize: 20 }));
  const latest = runs.data?.data.find((r) => r.status === 'SUCCEEDED') ?? null;
  const running = runs.data?.data.some((r) => !isTerminal(r.status)) ?? false;
  const equity = useQuery(equityQueryOptions(latest?.id ?? '', latest !== null));

  const up = latest?.summary ? Number(latest.summary.totalReturn) >= 0 : true;
  const title = market ? `${market.symbols.join(', ')} ${market.timeframe}` : 'No market';

  return (
    <div className={CARD_CLASS}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link href={`/strategies/${strategy.id}`} className="block truncate text-base font-semibold hover:underline">
            {strategy.name}
          </Link>
          <div className="text-muted-foreground mt-0.5 truncate text-xs">{title}</div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {strategy.latestVersion && <Pill>V{strategy.latestVersion.version}</Pill>}
          <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="ghost" size="icon-sm" aria-label="Actions" />}>
              <RiMore2Line />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => router.push(`/strategies/${strategy.id}`)}>Open</DropdownMenuItem>
              <DropdownMenuItem onClick={() => router.push(`/strategies/${strategy.id}/backtest`)}>
                New backtest
              </DropdownMenuItem>
              <DropdownMenuItem variant="destructive" onClick={onArchive}>
                Archive
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <ChartWell
        values={equity.data?.points.map((p) => Number(p.equity))}
        up={up}
        loading={runs.isPending || (latest !== null && equity.isPending)}
        empty={latest ? 'No closed trades' : 'No backtest yet'}
        badge={
          running ? (
            <WellBadge>
              <RiLoader4Line className="size-3 animate-spin" /> Running
            </WellBadge>
          ) : undefined
        }
      />

      <BacktestMetrics summary={latest?.summary ?? null} />

      <div className="mt-auto flex items-center justify-between gap-2 pt-1">
        <span className="text-muted-foreground text-xs" title={strategy.updatedAt}>
          Updated {timeAgo(strategy.updatedAt)}
        </span>
        {latest ? (
          <Link href={`/backtests/${latest.id}`} className={buttonVariants({ variant: 'outline', size: 'sm' })}>
            View report <RiArrowRightLine />
          </Link>
        ) : (
          <Link
            href={`/strategies/${strategy.id}/backtest`}
            className={buttonVariants({ variant: 'outline', size: 'sm' })}
          >
            Run backtest <RiArrowRightLine />
          </Link>
        )}
      </div>
    </div>
  );
}
