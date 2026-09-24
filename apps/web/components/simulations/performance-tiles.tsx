import type { SimulationSnapshot } from '@quant/contracts/simulation';

import { Tile, toneOf } from '@/components/backtests/summary-tiles';
import { money, percent } from '@/lib/format';

const signed = (value: string) => `${Number(value) > 0 ? '+' : ''}${money(value)}`;

/** Equity and P&L against the recorded starting balance. Realized is P&L less the open position. */
export function PerformanceTiles({ snapshot }: { snapshot: SimulationSnapshot }) {
  const quote = snapshot.quoteCurrency ?? '';
  const { baseline, pnl, returnPercent, realizedPnl, unrealizedPnl } = snapshot;

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Tile
        label="Equity"
        value={snapshot.equity ? `${money(snapshot.equity)} ${quote}` : '—'}
        hint={baseline ? `from ${money(baseline.amount)} ${baseline.currency}` : 'Starting balance not recorded yet'}
      />
      <Tile
        label="Profit / loss"
        value={pnl ? `${signed(pnl)} ${quote}` : '—'}
        hint={returnPercent ? percent(returnPercent, true) : undefined}
        tone={pnl ? toneOf(pnl) : undefined}
      />
      <Tile
        label="Unrealized"
        value={`${signed(unrealizedPnl)} ${quote}`}
        hint={snapshot.position ? 'Open position at the last close' : 'No open position'}
        tone={toneOf(unrealizedPnl)}
      />
      <Tile
        label="Realized"
        value={realizedPnl ? `${signed(realizedPnl)} ${quote}` : '—'}
        hint="Closed trades, after fees"
        tone={realizedPnl ? toneOf(realizedPnl) : undefined}
      />
    </div>
  );
}
