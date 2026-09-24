'use client';

import type { Simulation } from '@quant/contracts/simulation';
import {
  RiAlarmWarningLine,
  RiEqualizerLine,
  RiErrorWarningLine,
  RiExchangeLine,
  RiHistoryLine,
  RiLineChartLine,
  RiLoader4Line,
  RiServerLine,
  RiSettings3Line,
  RiTimeLine,
} from '@remixicon/react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useParams } from 'next/navigation';

import { shortTimeframe, symbolOf } from '@/components/metric-card';
import { Chip, PageHeader, SectionTitle } from '@/components/page-header';
import { ActivityFeed } from '@/components/simulations/activity-feed';
import { DetailRow as Row } from '@/components/simulations/detail-row';
import { EquityCurve } from '@/components/simulations/equity-curve';
import { FillTable } from '@/components/simulations/fill-table';
import { PerformanceTiles } from '@/components/simulations/performance-tiles';
import { PositionCard } from '@/components/simulations/position-card';
import { SimulationActions } from '@/components/simulations/simulation-actions';
import { StateBadge, simState } from '@/components/simulations/state-badge';
import { StrategyStatusCard } from '@/components/simulations/strategy-status';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorState } from '@/components/page-states';
import { Skeleton } from '@/components/ui/skeleton';
import {
  isStarting,
  simulationEquityQueryOptions,
  simulationEventsQueryOptions,
  simulationQueryOptions,
  simulationSnapshotQueryOptions,
} from '@/lib/api/simulations/simulation-queries';
import { strategyQueryOptions } from '@/lib/api/strategies/strategy-queries';
import { money, timeAgo, utcDateTime } from '@/lib/format';
import { cn } from '@/lib/utils';

/** Balances, position, the strategy's reasoning, the curve and the feed. */
function LiveState({ sim }: { sim: Simulation }) {
  const client = useQueryClient();
  const snapshot = useQuery(simulationSnapshotQueryOptions(sim.id));
  const events = useQuery(simulationEventsQueryOptions(client, sim.id));
  const equity = useQuery(simulationEquityQueryOptions(client, sim.id));
  const snap = snapshot.data;

  if (snapshot.isPending) return <Skeleton className="h-64 w-full" />;

  if (!snap) {
    const running = sim.live?.desired.status === 'RUNNING';
    return isStarting(snapshot.error) ? (
      <Alert>
        {running ? <RiLoader4Line className="animate-spin" /> : <RiTimeLine />}
        <AlertTitle>{running ? 'Waiting for the first report' : 'No report yet'}</AlertTitle>
        <AlertDescription>
          {running
            ? 'The node reports its balances and strategy every few seconds once it is up.'
            : 'Start the simulation to see its balances, position and strategy.'}
        </AlertDescription>
      </Alert>
    ) : (
      <ErrorState
        error={snapshot.error}
        title="Could not load the account state"
        onRetry={() => void snapshot.refetch()}
      />
    );
  }

  const quote = snap.quoteCurrency ?? '';

  return (
    <>
      {snap.stale && (
        <Alert variant="destructive">
          <RiErrorWarningLine />
          <AlertTitle>Showing the last report, from {timeAgo(snap.at)}</AlertTitle>
          <AlertDescription>The node has stopped reporting. These numbers are not live.</AlertDescription>
        </Alert>
      )}

      <PerformanceTiles snapshot={snap} />

      <div className="grid gap-6 md:grid-cols-2">
        <PositionCard snapshot={snap} />
        <StrategyStatusCard status={snap.strategy} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            <SectionTitle icon={RiLineChartLine}>Equity</SectionTitle>
          </CardTitle>
          <CardDescription>Marked to each bar&apos;s close. The dashed line is the starting balance.</CardDescription>
        </CardHeader>
        <CardContent>
          {equity.data && equity.data.points.length > 0 ? (
            <EquityCurve
              points={equity.data.points}
              baseline={snap.baseline ? Number(snap.baseline.amount) : null}
              quote={quote}
            />
          ) : (
            <p className="text-sm text-muted-foreground">The curve starts at the first closed bar.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            <SectionTitle icon={RiExchangeLine} tone="cyan">
              Fills
            </SectionTitle>
          </CardTitle>
          <CardDescription>Every fill, kept permanently. Fees include slippage.</CardDescription>
        </CardHeader>
        <CardContent>
          <FillTable simulationId={sim.id} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            <SectionTitle icon={RiHistoryLine} tone="violet">
              Activity
            </SectionTitle>
          </CardTitle>
          <CardDescription>Fills, signals, blocked entries, starts and stops. Times in UTC.</CardDescription>
        </CardHeader>
        <CardContent>
          {events.error ? (
            <ErrorState error={events.error} title="Could not load activity" onRetry={() => void events.refetch()} />
          ) : events.data ? (
            <ActivityFeed events={events.data.events} />
          ) : (
            <Skeleton className="h-32 w-full" />
          )}
        </CardContent>
      </Card>
    </>
  );
}

export default function SimulationPage() {
  const { id } = useParams<{ id: string }>();
  const { data: sim, isPending, error, refetch } = useQuery(simulationQueryOptions(id));
  const strategy = useQuery({ ...strategyQueryOptions(sim?.strategyId ?? ''), enabled: !!sim });

  if (isPending) {
    return (
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-8 w-72" />
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-64 w-full rounded-2xl" />
      </div>
    );
  }

  if (error || !sim) {
    return (
      <ErrorState
        error={error}
        title="Could not load this simulation"
        onRetry={() => void refetch()}
        back={{ href: '/simulations', label: 'Back to simulations' }}
        notFound={{
          code: 'SIMULATION_NOT_FOUND',
          title: 'Simulation not found',
          description: 'It may belong to another account.',
        }}
      />
    );
  }

  const live = sim.live;
  const observed = live?.observed ?? null;
  const state = simState(sim);
  const quote = /(USDT|USDC|FDUSD|BTC|ETH)\.[A-Z]+$/.exec(sim.instrumentId)?.[1] ?? ''; // SOLUSDT.BINANCE -> USDT
  const risk = sim.risk ?? {};
  const limit = (value: string | number | undefined, unit = quote) =>
    value === undefined ? <span className="text-muted-foreground">No limit</span> : `${money(value, 0)} ${unit}`.trim();

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader
        back={{ href: '/simulations', label: 'Simulations' }}
        title={sim.name}
        badges={<StateBadge sim={sim} />}
        chips={
          <>
            <Chip className="text-foreground font-medium">
              {symbolOf(sim.instrumentId)} · {shortTimeframe(sim.barType)}
            </Chip>
            <Chip>
              <Link href={`/strategies/${sim.strategyId}`} className="hover:text-foreground">
                {sim.strategyName}
              </Link>{' '}
              v{sim.version}
            </Chip>
            <Chip>Paper trading</Chip>
            <Chip>
              <span className="relative flex size-1.5">
                {state.label === 'Running' && (
                  <span className="absolute inset-0 animate-ping rounded-full bg-emerald-500/60" />
                )}
                <span
                  className={cn(
                    'relative size-1.5 rounded-full',
                    state.label === 'Running' ? 'bg-emerald-500' : 'bg-muted-foreground/50'
                  )}
                />
              </span>
              {observed?.heartbeatAt ? `Heartbeat ${timeAgo(observed.heartbeatAt)}` : 'No heartbeat yet'}
            </Chip>
          </>
        }
      />

      {observed?.status === 'HALTED' && (
        <Alert variant="destructive">
          <RiErrorWarningLine />
          <AlertTitle>Halted: needs an operator</AlertTitle>
          <AlertDescription>
            On startup the node disagreed with the exchange about what the account holds. It will not retry by itself,
            because retrying would not change the facts. Check the account, then use{' '}
            <strong>Restate and restart</strong>.
          </AlertDescription>
        </Alert>
      )}
      {live?.killSwitch === 'ENGAGED' && (
        <Alert variant="destructive">
          <RiAlarmWarningLine />
          <AlertTitle>Kill switch on</AlertTitle>
          <AlertDescription>
            Every order is blocked, exits included. Any open position is not being managed. Release it to let the
            strategy trade again.
          </AlertDescription>
        </Alert>
      )}
      {live?.heartbeatStale && observed?.status !== 'HALTED' && (
        <Alert variant="destructive">
          <RiErrorWarningLine />
          <AlertTitle>Not heartbeating</AlertTitle>
          <AlertDescription>
            Last heartbeat {observed?.heartbeatAt ? timeAgo(observed.heartbeatAt) : 'never'}. The supervisor presumes
            the node dead after 90 seconds and restarts it.
          </AlertDescription>
        </Alert>
      )}

      <LiveState sim={sim} />

      <Card>
        <CardHeader>
          <CardTitle>
            <SectionTitle icon={RiSettings3Line} tone="amber">
              Controls
            </SectionTitle>
          </CardTitle>
          <CardDescription>{state.hint}</CardDescription>
        </CardHeader>
        <CardContent>
          <SimulationActions
            key={sim.versionId}
            sim={sim}
            versions={strategy.data?.versions ?? []} // Empty (no switching) if the strategy was archived.
          />
        </CardContent>
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>
              <SectionTitle icon={RiServerLine} tone="cyan">
                State
              </SectionTitle>
            </CardTitle>
            <CardDescription>
              What was asked for, and what the node reports. They match when it has converged.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!live ? (
              <p className="text-sm text-muted-foreground">{sim.liveError?.message ?? 'No report from the engine.'}</p>
            ) : (
              <>
                <Row label="Asked for">
                  {live.desired.status} · revision {live.desired.revision}
                </Row>
                <Row label="Node reports">
                  {observed ? `${observed.status} · revision ${observed.revision}` : 'Not picked up yet'}
                  {live.converging && <RiLoader4Line className="ml-1.5 inline size-3.5 animate-spin" />}
                </Row>
                <Row label="Last heartbeat">
                  {observed?.heartbeatAt ? (
                    <span title={observed.heartbeatAt}>{timeAgo(observed.heartbeatAt)}</span>
                  ) : (
                    '—'
                  )}
                </Row>
                <Row label="Node started">{observed?.startedAt ? utcDateTime(observed.startedAt) + ' UTC' : '—'}</Row>
                <Row label="Kill switch">{live.killSwitch === 'ENGAGED' ? 'On' : 'Off'}</Row>
                <Row label="Held by">{live.leaseHolder ?? '—'}</Row>
                {observed?.error && (
                  <Row label="Last error">
                    <code className="text-xs">
                      {typeof observed.error.code === 'string'
                        ? `${observed.error.code}: ${String(observed.error.message ?? '')}`
                        : JSON.stringify(observed.error)}
                    </code>
                  </Row>
                )}
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>
              <SectionTitle icon={RiEqualizerLine} tone="violet">
                Configuration
              </SectionTitle>
            </CardTitle>
            <CardDescription>Account-level. Fixed when it was created.</CardDescription>
          </CardHeader>
          <CardContent>
            <Row label="Bars">{sim.barType}</Row>
            <Row label="Fees (maker / taker)">
              {sim.fees.makerBps} / {sim.fees.takerBps} bps
            </Row>
            <Row label="Slippage">{sim.slippageBps} bps</Row>
            <Row label="Max order size">{limit(risk.maxOrderNotional)}</Row>
            <Row label="Max position size">{limit(risk.maxPositionNotional)}</Row>
            <Row label="Daily loss limit">{limit(risk.dailyLossLimit)}</Row>
            <Row label="Max open positions">{limit(risk.maxOpenPositions, '')}</Row>
            <Row label="Account id">
              <code className="text-xs">{sim.accountId}</code>
            </Row>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
