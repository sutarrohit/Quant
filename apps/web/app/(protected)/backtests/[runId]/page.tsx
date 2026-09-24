'use client';

import { isTerminal } from '@quant/contracts/backtest';
import {
  RiCalendarLine,
  RiErrorWarningLine,
  RiExchangeLine,
  RiLineChartLine,
  RiPulseLine,
  RiRepeatLine,
} from '@remixicon/react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useParams } from 'next/navigation';

import { EquityChart } from '@/components/backtests/equity-chart';
import { StatusBadge, StatusTimeline } from '@/components/backtests/run-status';
import { SummaryTiles } from '@/components/backtests/summary-tiles';
import { Pill, shortTimeframe, symbolOf } from '@/components/metric-card';
import { Chip, PageHeader, SectionTitle } from '@/components/page-header';
import { TradeTable } from '@/components/backtests/trade-table';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorState } from '@/components/page-states';
import { Skeleton } from '@/components/ui/skeleton';
import {
  backtestQueryOptions,
  cancelBacktestMutationOptions,
  equityQueryOptions,
} from '@/lib/api/backtests/backtest-queries';
import { utcDate } from '@/lib/format';
import { toastError } from '@/utils/toast-error';

const quoteOf = (balances: string[]) => balances[0]?.split(' ')[1] ?? '';

export default function BacktestRunPage() {
  const { runId } = useParams<{ runId: string }>();
  const client = useQueryClient();
  const { data: run, isPending, error, refetch } = useQuery(backtestQueryOptions(runId));
  const succeeded = run?.status === 'SUCCEEDED';
  const equity = useQuery(equityQueryOptions(runId, succeeded));
  const cancel = useMutation({
    ...cancelBacktestMutationOptions(client),
    onError: (e) => toastError(e),
  });

  if (isPending) {
    return (
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-4">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-8 w-72" />
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-96 w-full rounded-2xl" />
      </div>
    );
  }

  if (error || !run) {
    return (
      <ErrorState
        error={error}
        title="Could not load this run"
        onRetry={() => void refetch()}
        back={{ href: '/backtests', label: 'Back to backtests' }}
        notFound={{ code: 'RUN_NOT_FOUND', title: 'Run not found', description: 'It may belong to another account.' }}
      />
    );
  }

  const quote = quoteOf(run.startingBalances);
  const finished = isTerminal(run.status);

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
      <PageHeader
        back={{ href: '/backtests', label: 'Backtests' }}
        title={
          <Link href={`/strategies/${run.strategyId}`} className="hover:underline">
            {run.strategyName}
          </Link>
        }
        badges={
          <>
            <Pill>V{run.version}</Pill>
            <StatusBadge status={run.status} />
          </>
        }
        chips={
          <>
            <Chip className="text-foreground font-medium">
              {symbolOf(run.instrumentId)} · {shortTimeframe(run.barType)}
            </Chip>
            <Chip>
              <RiCalendarLine className="size-3" /> {utcDate(run.start)} → {utcDate(run.end)} UTC
            </Chip>
            <Chip>
              Fees {run.fees.makerBps}/{run.fees.takerBps} bps
            </Chip>
            <Chip>Slippage {run.slippageBps} bps</Chip>
            <Chip>Start {run.startingBalances.join(', ')}</Chip>
          </>
        }
        actions={
          <>
            {run.status === 'QUEUED' && (
              <Button variant="outline" size="sm" disabled={cancel.isPending} onClick={() => cancel.mutate(run.id)}>
                {cancel.isPending ? 'Cancelling…' : 'Cancel run'}
              </Button>
            )}
            {finished && (
              <Link
                href={`/strategies/${run.strategyId}/backtest?version=${run.versionId}`}
                className={buttonVariants({ variant: 'outline', size: 'sm' })}
              >
                <RiRepeatLine /> Run again
              </Link>
            )}
            {succeeded && (
              <Link
                href={`/strategies/${run.strategyId}/simulate?version=${run.versionId}`}
                className={buttonVariants({ size: 'sm' })}
              >
                <RiPulseLine /> Paper trade this version
              </Link>
            )}
          </>
        }
      />

      {!finished && (
        <Card>
          <CardContent className="flex flex-col gap-3">
            <StatusTimeline status={run.status} />
            <p className="text-sm text-muted-foreground">
              {run.status === 'SUBMITTING'
                ? 'The engine has not confirmed the run yet. It is retried automatically, as the same run.'
                : run.status === 'FETCHING_DATA'
                  ? 'Downloading market data the engine does not hold yet. A long window can take a few minutes.'
                  : 'This page updates by itself.'}
            </p>
          </CardContent>
        </Card>
      )}

      {run.error && (
        <Alert variant="destructive">
          <RiErrorWarningLine />
          <AlertTitle>{run.status === 'CANCELLED' ? 'Cancelled' : `Failed: ${run.error.code}`}</AlertTitle>
          <AlertDescription>{run.error.message}</AlertDescription>
        </Alert>
      )}
      {run.status === 'CANCELLED' && !run.error && (
        <p className="text-sm text-muted-foreground">Cancelled before it started. Nothing ran.</p>
      )}

      {run.summary && <SummaryTiles summary={run.summary} quote={quote} />}

      {succeeded && (
        <Card>
          <CardHeader>
            <CardTitle>
              <SectionTitle icon={RiLineChartLine}>Equity</SectionTitle>
            </CardTitle>
            <CardDescription>
              Realized: it moves only when a trade closes.
              {equity.data &&
                equity.data.total > equity.data.points.length &&
                ` ${equity.data.points.length} of ${equity.data.total} points shown.`}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {equity.isPending && <Skeleton className="h-96 w-full rounded-xl" />}
            {equity.error && (
              <p className="text-sm text-destructive">Could not load the curve: {equity.error.message}</p>
            )}
            {equity.data &&
              (equity.data.points.length > 0 ? (
                <EquityChart points={equity.data.points} quote={quote} />
              ) : (
                <p className="py-8 text-center text-sm text-muted-foreground">No closed trades, so nothing to draw.</p>
              ))}
          </CardContent>
        </Card>
      )}

      {succeeded && (
        <Card>
          <CardHeader>
            <CardTitle>
              <SectionTitle icon={RiExchangeLine} tone="cyan">
                Trades
              </SectionTitle>
            </CardTitle>
            <CardDescription>Closed round trips, with the fees and slippage each one paid.</CardDescription>
          </CardHeader>
          <CardContent>
            <TradeTable runId={run.id} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
