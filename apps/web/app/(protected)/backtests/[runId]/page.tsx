'use client';

import { isTerminal } from '@quant/contracts/backtest';
import { RiErrorWarningLine, RiPulseLine, RiRepeatLine } from '@remixicon/react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { toast } from 'sonner';

import { EquityChart } from '@/components/backtests/equity-chart';
import { StatusBadge, StatusTimeline } from '@/components/backtests/run-status';
import { SummaryTiles } from '@/components/backtests/summary-tiles';
import { TradeTable } from '@/components/backtests/trade-table';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  backtestQueryOptions,
  cancelBacktestMutationOptions,
  equityQueryOptions,
} from '@/lib/api/backtests/backtest-queries';
import { utcDate } from '@/lib/format';
import { ApiError } from '@/utils/api-error';

const quoteOf = (balances: string[]) => balances[0]?.split(' ')[1] ?? '';

export default function BacktestRunPage() {
  const { runId } = useParams<{ runId: string }>();
  const client = useQueryClient();
  const { data: run, isPending, error } = useQuery(backtestQueryOptions(runId));
  const succeeded = run?.status === 'SUCCEEDED';
  const equity = useQuery(equityQueryOptions(runId, succeeded));
  const cancel = useMutation({
    ...cancelBacktestMutationOptions(client),
    onError: (e) => toast.error(e.message),
  });

  if (isPending) {
    return (
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  if (error || !run) {
    const missing = error instanceof ApiError && error.code === 'RUN_NOT_FOUND';
    return (
      <div className="mx-auto flex max-w-md flex-col items-center gap-3 py-16 text-center">
        <p className="font-medium">{missing ? 'Run not found' : 'Could not load this run'}</p>
        {!missing && <p className="text-sm text-muted-foreground">{error?.message}</p>}
        <Link href="/backtests" className="text-sm underline underline-offset-2">
          Back to backtests
        </Link>
      </div>
    );
  }

  const quote = quoteOf(run.startingBalances);
  const finished = isTerminal(run.status);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold">
              <Link href={`/strategies/${run.strategyId}`} className="hover:underline">
                {run.strategyName}
              </Link>{' '}
              <span className="text-muted-foreground">v{run.version}</span>
            </h1>
            <StatusBadge status={run.status} />
          </div>
          <p className="text-sm text-muted-foreground">
            {run.instrumentId.replace(/\.[A-Z]+$/, '')} · {utcDate(run.start)} → {utcDate(run.end)} UTC · fees{' '}
            {run.fees.makerBps}/{run.fees.takerBps} bps maker/taker · slippage {run.slippageBps} bps
          </p>
        </div>
        <div className="flex gap-2">
          {run.status === 'QUEUED' && (
            <Button variant="outline" size="sm" disabled={cancel.isPending} onClick={() => cancel.mutate(run.id)}>
              {cancel.isPending ? 'Cancelling…' : 'Cancel'}
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
        </div>
      </div>

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
            <CardTitle>Equity</CardTitle>
            <CardDescription>
              Realized: it moves only when a trade closes.
              {equity.data &&
                equity.data.total > equity.data.points.length &&
                ` ${equity.data.points.length} of ${equity.data.total} points shown.`}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {equity.isPending && <Skeleton className="h-96 w-full" />}
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
            <CardTitle>Trades</CardTitle>
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
