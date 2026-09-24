import type { StrategyStatus } from '@quant/contracts/simulation';
import { RiCheckLine, RiCloseLine, RiCpuLine } from '@remixicon/react';

import { SectionTitle } from '@/components/page-header';
import { DetailRow } from '@/components/simulations/detail-row';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { barClose, barSeconds } from '@/lib/bars';
import { duration, money, utcDateTime } from '@/lib/format';

const PHASES = {
  WARMING_UP: { label: 'Warming up', hint: 'Collecting bars until every indicator has a value.' },
  WAITING_FOR_ENTRY: { label: 'Waiting for entry', hint: 'Flat. Checks the entry rule on every closed bar.' },
  IN_POSITION: { label: 'In position', hint: 'Holding. Checks the exit rule on every closed bar.' },
} as const;

/** Indicator values are floats from the engine; show a readable precision. */
const reading = (value: string) => {
  const n = Number(value);
  return Math.abs(n) >= 1_000 ? money(n, 0) : n.toFixed(Math.abs(n) >= 1 ? 2 : 4);
};

/** What the strategy is waiting for, and which half of its rule is holding it back. */
export function StrategyStatusCard({ status }: { status: StrategyStatus | null }) {
  if (!status) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>
            <SectionTitle icon={RiCpuLine} tone="violet">
              Strategy
            </SectionTitle>
          </CardTitle>
          <CardDescription>Not reporting yet.</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const phase = PHASES[status.phase];
  const step = barSeconds(status.barType);
  const evaluation = status.lastEvaluation;
  const lastClose = status.lastBar ? barClose(status.lastBar.time) : null;
  const nextBar = lastClose && step ? new Date(Date.parse(lastClose) + step * 1000).toISOString() : null;
  const warm = Math.min(status.barsSeen, status.warmupBars);

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <SectionTitle icon={RiCpuLine} tone="violet">
            Strategy <Badge variant="secondary">{phase.label}</Badge>
          </SectionTitle>
        </CardTitle>
        <CardDescription>
          {phase.hint}
          {!!status.barsFromHistory && ` Warmed from ${status.barsFromHistory} past bars at start.`}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {status.phase === 'WARMING_UP' && (
          <div className="flex flex-col gap-1.5">
            <div
              className="h-2 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-label="Warm-up"
              aria-valuemin={0}
              aria-valuemax={status.warmupBars}
              aria-valuenow={warm}
            >
              <div
                className="h-full bg-gradient-to-r from-emerald-500 to-cyan-400"
                style={{ width: `${(warm / Math.max(status.warmupBars, 1)) * 100}%` }}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              {warm} of {status.warmupBars} bars
              {step && status.warmupBars > warm && ` · about ${duration((status.warmupBars - warm) * step)} to go`}.
              {status.barsFromHistory ? '' : ' Past bars could not be loaded, so it waits for new ones.'}
            </p>
          </div>
        )}

        {evaluation && (
          <div>
            <p className="text-muted-foreground text-[10px] font-medium tracking-wider uppercase">
              {evaluation.side === 'entry' ? 'Entry' : 'Exit'} rule on the last bar
            </p>
            <ul className="mt-1 flex flex-col">
              {evaluation.conditions.map((c) => (
                <li key={c.path} className="flex items-center gap-2 border-b py-2 text-sm last:border-0">
                  {c.passed ? (
                    <RiCheckLine
                      className="size-4 shrink-0 text-emerald-700 dark:text-emerald-400"
                      aria-label="holds"
                    />
                  ) : (
                    <RiCloseLine className="size-4 shrink-0 text-muted-foreground" aria-label="does not hold" />
                  )}
                  <code className="flex-1 text-xs">{c.label}</code>
                  {c.series && status.values[c.series] !== undefined && (
                    <span className="text-xs tabular-nums text-muted-foreground">
                      now {reading(status.values[c.series]!)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div>
          <DetailRow label="Last bar">
            {status.lastBar && lastClose
              ? `${utcDateTime(lastClose)} UTC · close ${money(status.lastBar.close)}`
              : 'None yet'}
          </DetailRow>
          <DetailRow label="Next bar">{nextBar ? `${utcDateTime(nextBar)} UTC` : '—'}</DetailRow>
          <DetailRow label="Orders submitted">{status.ordersSubmitted}</DetailRow>
          <DetailRow label="Entries blocked">{status.ordersBlocked}</DetailRow>
        </div>
      </CardContent>
    </Card>
  );
}
