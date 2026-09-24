import type { BacktestSummary } from '@quant/contracts/backtest';
import { RiInformationLine } from '@remixicon/react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { cn } from '@/lib/utils';
import { duration, money, percent } from '@/lib/format';

export function Tile({
  label,
  value,
  hint,
  tone,
  size = 'md',
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: 'up' | 'down';
  size?: 'md' | 'lg'; // lg: the headline numbers at the top of a page.
}) {
  return (
    <div
      className={cn(
        'bg-card flex min-w-0 flex-col gap-1 rounded-xl border',
        size === 'lg' ? 'relative overflow-hidden p-4 sm:p-5' : 'p-3'
      )}
    >
      {/* Tinted wash behind a headline number, so gains and losses read at a glance. */}
      {size === 'lg' && tone && (
        <div
          aria-hidden
          className={cn(
            'pointer-events-none absolute inset-0 bg-gradient-to-br to-transparent',
            tone === 'up' ? 'from-emerald-500/10' : 'from-red-500/10'
          )}
        />
      )}
      <span className="text-muted-foreground relative text-[10px] font-medium tracking-wider uppercase">{label}</span>
      <span
        className={cn(
          'relative truncate font-semibold tabular-nums',
          size === 'lg' ? 'text-2xl tracking-tight' : 'text-base',
          tone === 'up' && 'text-emerald-600 dark:text-emerald-400',
          tone === 'down' && 'text-red-600 dark:text-red-400'
        )}
      >
        {value}
      </span>
      {hint && <span className="text-muted-foreground relative text-xs">{hint}</span>}
    </div>
  );
}

export const toneOf = (value: string) => (Number(value) > 0 ? 'up' : Number(value) < 0 ? 'down' : undefined);

/** The run's numbers. Costs sit beside the return, not in a drawer: they are the honest half of it. */
export function SummaryTiles({ summary, quote }: { summary: BacktestSummary; quote: string }) {
  const open = summary.openPositions > 0;

  return (
    <div className="flex flex-col gap-4">
      {open && (
        <Alert>
          <RiInformationLine />
          <AlertTitle>
            {summary.openPositions} position{summary.openPositions > 1 ? 's' : ''} still open at the end
          </AlertTitle>
          <AlertDescription>
            Ending equity marks {summary.openPositions > 1 ? 'them' : 'it'} to the last close (
            {money(summary.unrealizedPnl)} {quote} unrealized). The equity curve and trade table show closed trades
            only.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile
          size="lg"
          label="Total return"
          value={percent(summary.totalReturn, true)}
          tone={toneOf(summary.totalReturn)}
          hint={`CAGR ${percent(summary.cagr, true)}`}
        />
        <Tile
          size="lg"
          label="Ending equity"
          value={`${money(summary.endingEquity)} ${quote}`}
          hint={`from ${money(summary.startingEquity)}${open ? ' · incl. unrealized' : ''}`}
        />
        <Tile size="lg" label="Max drawdown" value={percent(summary.maxDrawdown)} tone="down" />
        <Tile
          size="lg"
          label="Sharpe"
          value={Number(summary.sharpe).toFixed(2)}
          hint={`Sortino ${Number(summary.sortino).toFixed(2)}`}
        />
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Tile label="Trades" value={String(summary.tradeCount)} hint={`${percent(summary.winRate)} won`} />
        <Tile label="Profit factor" value={Number(summary.profitFactor).toFixed(2)} />
        <Tile
          label="Average trade"
          value={`${money(summary.averageTrade)} ${quote}`}
          hint={`median ${money(summary.medianTrade)}`}
          tone={toneOf(summary.averageTrade)}
        />
        <Tile
          label="Time in market"
          value={percent(summary.exposurePercent)}
          hint={`avg hold ${duration(summary.averageHoldingSeconds)}`}
        />
        <Tile label="Total fees" value={`${money(summary.totalFees)} ${quote}`} hint="Already deducted" />
        <Tile label="Total slippage" value={`${money(summary.totalSlippage)} ${quote}`} hint="Already deducted" />
      </div>
    </div>
  );
}
