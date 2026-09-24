import type { SimulationSnapshot } from '@quant/contracts/simulation';
import { RiWallet3Line } from '@remixicon/react';

import { SectionTitle } from '@/components/page-header';
import { DetailRow } from '@/components/simulations/detail-row';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { duration, money, percent, utcDateTime } from '@/lib/format';

const base = (instrumentId: string, quote: string) =>
  instrumentId.replace(/\.[A-Z]+$/, '').replace(new RegExp(`${quote}$`), '');

/** The open position, or flat, with what the account holds either way. */
export function PositionCard({ snapshot }: { snapshot: SimulationSnapshot }) {
  const quote = snapshot.quoteCurrency ?? '';
  const coin = base(snapshot.instrumentId, quote);
  const position = snapshot.position;
  const move =
    position?.lastPrice != null
      ? ((Number(position.lastPrice) - Number(position.avgEntry)) / Number(position.avgEntry)) * 100
      : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <SectionTitle icon={RiWallet3Line}>Position</SectionTitle>
        </CardTitle>
        <CardDescription>
          {position ? `${position.side} since ${utcDateTime(position.openedAt)} UTC` : 'Flat: holding no coin.'}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {position && (
          <>
            <DetailRow label="Quantity">
              {money(position.quantity, 3)} {coin}
            </DetailRow>
            <DetailRow label="Average entry">
              {money(position.avgEntry)} {quote}
            </DetailRow>
            <DetailRow label="Last price">
              {position.lastPrice ? `${money(position.lastPrice)} ${quote}` : '—'}
            </DetailRow>
            <DetailRow label="Unrealized">
              <span
                className={cn(
                  Number(position.unrealizedPnl) > 0 && 'text-emerald-700 dark:text-emerald-400',
                  Number(position.unrealizedPnl) < 0 && 'text-destructive'
                )}
              >
                {money(position.unrealizedPnl)} {quote}
                {move !== null && ` (${percent(move, true)})`}
              </span>
            </DetailRow>
            <DetailRow label="Stop loss at">
              {position.stopPrice ? `${money(position.stopPrice)} ${quote}` : '—'}
            </DetailRow>
            <DetailRow label="Take profit at">
              {position.takeProfitPrice ? `${money(position.takeProfitPrice)} ${quote}` : '—'}
            </DetailRow>
            <DetailRow label="Held for">
              {duration((Date.parse(snapshot.at) - Date.parse(position.openedAt)) / 1000)}
            </DetailRow>
          </>
        )}

        <p className={cn('text-muted-foreground text-[10px] font-medium tracking-wider uppercase', position && 'mt-4')}>
          Balances
        </p>
        {snapshot.balances.length === 0 && <p className="py-2 text-sm text-muted-foreground">Nothing held.</p>}
        {[...snapshot.balances, ...snapshot.otherHoldings].map((b) => (
          <DetailRow key={b.currency} label={b.currency}>
            {money(b.total, b.currency === quote ? 2 : 3)}
            {Number(b.locked) > 0 && <span className="text-muted-foreground"> ({money(b.locked, 3)} locked)</span>}
          </DetailRow>
        ))}
        {snapshot.otherHoldings.length > 0 && (
          <p className="pt-2 text-xs text-muted-foreground">
            Only {quote} and {coin} count towards equity; the strategy does not trade the rest.
          </p>
        )}
        {snapshot.openOrders.length > 0 && (
          <p className="pt-2 text-xs text-muted-foreground">
            {snapshot.openOrders.length} open order{snapshot.openOrders.length > 1 ? 's' : ''} waiting to fill.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
