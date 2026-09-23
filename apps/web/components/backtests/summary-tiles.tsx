import type { BacktestSummary } from '@quant/contracts/backtest';
import { RiInformationLine } from '@remixicon/react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { cn } from '@/lib/utils';
import { duration, money, percent } from '@/lib/format';

function Tile({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: 'up' | 'down' }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border p-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span
        className={cn(
          'text-lg font-semibold tabular-nums',
          tone === 'up' && 'text-emerald-600 dark:text-emerald-400',
          tone === 'down' && 'text-destructive'
        )}
      >
        {value}
      </span>
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </div>
  );
}

const toneOf = (value: string) => (Number(value) > 0 ? 'up' : Number(value) < 0 ? 'down' : undefined);

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

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label="Total return" value={percent(summary.totalReturn, true)} tone={toneOf(summary.totalReturn)} />
        <Tile
          label="Ending equity"
          value={`${money(summary.endingEquity)} ${quote}`}
          hint={`from ${money(summary.startingEquity)}${open ? ' · incl. unrealized' : ''}`}
        />
        <Tile label="Max drawdown" value={percent(summary.maxDrawdown)} tone="down" />
        <Tile label="CAGR" value={percent(summary.cagr, true)} tone={toneOf(summary.cagr)} />

        <Tile label="Total fees" value={`${money(summary.totalFees)} ${quote}`} hint="Already deducted" />
        <Tile label="Total slippage" value={`${money(summary.totalSlippage)} ${quote}`} hint="Already deducted" />
        <Tile label="Trades" value={String(summary.tradeCount)} hint={`${percent(summary.winRate)} won`} />
        <Tile label="Profit factor" value={Number(summary.profitFactor).toFixed(2)} />

        <Tile label="Sharpe" value={Number(summary.sharpe).toFixed(2)} />
        <Tile label="Sortino" value={Number(summary.sortino).toFixed(2)} />
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
      </div>
    </div>
  );
}
