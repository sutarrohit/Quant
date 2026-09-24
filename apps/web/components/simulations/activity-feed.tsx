'use client';

import type { SimulationEvent } from '@quant/contracts/simulation';
import {
  RiAlarmWarningLine,
  RiArrowDownLine,
  RiArrowUpLine,
  RiFlashlightLine,
  RiForbidLine,
  RiInformationLine,
  RiPlayLine,
  RiStopLine,
} from '@remixicon/react';
import { useState, type ReactNode } from 'react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { duration, money, utcDateTime } from '@/lib/format';

type Tone = 'good' | 'bad' | 'plain';
type Line = { icon: ReactNode; title: string; detail?: string; tone: Tone };

const str = (value: unknown) => (typeof value === 'string' || typeof value === 'number' ? String(value) : '');
const fee = (value: unknown) => {
  const c = value as { amount?: string; currency?: string } | undefined;
  return c?.amount ? `fee ${money(c.amount, 4)} ${c.currency ?? ''}`.trim() : '';
};
const signedMoney = (value: unknown) => {
  const c = value as { amount?: string; currency?: string } | undefined;
  const n = Number(c?.amount ?? 0);
  return `${n > 0 ? '+' : ''}${money(n)} ${c?.currency ?? ''}`.trim();
};
const humanize = (kind: string) => kind.charAt(0) + kind.slice(1).toLowerCase().replaceAll('_', ' ');

/** One event as a sentence. Unknown kinds still show, generically (L7). */
function describe(e: SimulationEvent): Line {
  switch (e.kind) {
    case 'NODE_STARTED':
      return { icon: <RiPlayLine />, title: 'Node started', detail: `revision ${str(e.revision)}`, tone: 'plain' };
    case 'NODE_STOPPED':
      return { icon: <RiStopLine />, title: 'Node stopped', tone: 'plain' };
    case 'SIGNAL':
      return {
        icon: <RiFlashlightLine />,
        title: `${e.side === 'exit' ? 'Exit' : 'Entry'} signal`,
        detail: `close ${money(str(e.close))}`,
        tone: 'plain',
      };
    case 'ENTRY_SUBMITTED':
      return {
        icon: <RiArrowUpLine />,
        title: `Buy order for ${str(e.quantity)}`,
        detail: `≈ ${money(str(e.notional))}`,
        tone: 'plain',
      };
    case 'EXIT_SUBMITTED':
      return { icon: <RiArrowDownLine />, title: `Sell order for ${str(e.quantity)}`, tone: 'plain' };
    case 'FILL':
      return {
        icon: e.side === 'SELL' ? <RiArrowDownLine /> : <RiArrowUpLine />,
        title: `${e.side === 'SELL' ? 'Sold' : 'Bought'} ${str(e.quantity)} @ ${money(str(e.price))}`,
        detail: fee(e.commission),
        tone: 'good',
      };
    case 'POSITION_CLOSED':
      return {
        icon: <RiInformationLine />,
        title: `Position closed ${signedMoney(e.realizedPnl)}`,
        detail: `${money(str(e.entryPrice))} → ${money(str(e.exitPrice))} · held ${duration(Number(e.durationSeconds ?? 0))}`,
        tone: Number((e.realizedPnl as { amount?: string } | undefined)?.amount ?? 0) >= 0 ? 'good' : 'bad',
      };
    case 'ENTRY_SKIPPED':
      return { icon: <RiInformationLine />, title: 'Entry skipped', detail: humanize(str(e.outcome)), tone: 'plain' };
    case 'ENTRY_BLOCKED':
      return { icon: <RiForbidLine />, title: 'Entry blocked', detail: str(e.reason), tone: 'bad' };
    case 'ORDER_REJECTED':
      return { icon: <RiForbidLine />, title: 'Order rejected', detail: str(e.reason), tone: 'bad' };
    case 'KILL_ENGAGED':
      return { icon: <RiAlarmWarningLine />, title: 'Kill switch on', tone: 'bad' };
    case 'KILL_RELEASED':
      return { icon: <RiAlarmWarningLine />, title: 'Kill switch released', tone: 'plain' };
    case 'MANDATE_REVOKED':
      return { icon: <RiForbidLine />, title: 'Trading authority revoked', tone: 'bad' };
    default:
      return { icon: <RiInformationLine />, title: humanize(e.kind), tone: 'plain' };
  }
}

const PAGE = 25;

/** Newest first. Fills, signals, blocked entries, starts and stops. */
export function ActivityFeed({ events }: { events: SimulationEvent[] }) {
  const [shown, setShown] = useState(PAGE);
  const newest = [...events].reverse();

  if (newest.length === 0) return <p className="text-sm text-muted-foreground">Nothing has happened yet.</p>;

  return (
    <div className="flex flex-col">
      <ol>
        {newest.slice(0, shown).map((event) => {
          const line = describe(event);
          return (
            <li
              key={event.id}
              className="border-border/60 flex items-start gap-3 border-b py-2.5 text-sm last:border-0"
            >
              <span
                className={cn(
                  'flex size-7 shrink-0 items-center justify-center rounded-full [&_svg]:size-3.5',
                  line.tone === 'good' && 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
                  line.tone === 'bad' && 'bg-red-500/10 text-red-600 dark:text-red-400',
                  line.tone === 'plain' && 'bg-muted text-muted-foreground'
                )}
              >
                {line.icon}
              </span>
              <div className="flex min-w-0 flex-1 flex-col">
                <span className="font-medium">{line.title}</span>
                {line.detail && <span className="text-xs text-muted-foreground">{line.detail}</span>}
              </div>
              <time dateTime={event.at} className="shrink-0 text-xs tabular-nums text-muted-foreground">
                {utcDateTime(event.at)}
              </time>
            </li>
          );
        })}
      </ol>
      {newest.length > shown && (
        <Button variant="ghost" size="sm" className="self-center" onClick={() => setShown((n) => n + PAGE)}>
          Show older
        </Button>
      )}
    </div>
  );
}
