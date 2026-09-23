'use client';

import { RiAlarmWarningLine, RiErrorWarningLine, RiLoader4Line } from '@remixicon/react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useParams } from 'next/navigation';

import { SimulationActions } from '@/components/simulations/simulation-actions';
import { StateBadge, simState } from '@/components/simulations/state-badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { simulationQueryOptions } from '@/lib/api/simulations/simulation-queries';
import { strategyQueryOptions } from '@/lib/api/strategies/strategy-queries';
import { money, timeAgo, utcDateTime } from '@/lib/format';
import { ApiError } from '@/utils/api-error';

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b py-2 text-sm last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right tabular-nums">{children}</span>
    </div>
  );
}

export default function SimulationPage() {
  const { id } = useParams<{ id: string }>();
  const { data: sim, isPending, error } = useQuery(simulationQueryOptions(id));
  const strategy = useQuery({ ...strategyQueryOptions(sim?.strategyId ?? ''), enabled: !!sim });

  if (isPending) {
    return (
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error || !sim) {
    const missing = error instanceof ApiError && error.code === 'SIMULATION_NOT_FOUND';
    return (
      <div className="mx-auto flex max-w-md flex-col items-center gap-3 py-16 text-center">
        <p className="font-medium">{missing ? 'Simulation not found' : 'Could not load this simulation'}</p>
        {!missing && <p className="text-sm text-muted-foreground">{error?.message}</p>}
        <Link href="/simulations" className="text-sm underline underline-offset-2">
          Back to simulations
        </Link>
      </div>
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
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold">{sim.name}</h1>
          <StateBadge sim={sim} />
        </div>
        <p className="text-sm text-muted-foreground">
          <Link href={`/strategies/${sim.strategyId}`} className="hover:underline">
            {sim.strategyName}
          </Link>{' '}
          v{sim.version} · {sim.instrumentId.replace(/\.[A-Z]+$/, '')} · paper, 10,000 USDT starting balance
        </p>
      </div>

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

      <Card>
        <CardHeader>
          <CardTitle>Controls</CardTitle>
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
            <CardTitle>State</CardTitle>
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
            <CardTitle>Configuration</CardTitle>
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
