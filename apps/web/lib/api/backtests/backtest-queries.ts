import { keepPreviousData, mutationOptions, queryOptions, type QueryClient } from '@tanstack/react-query';
import { isTerminal, type BacktestListQuery } from '@quant/contracts/backtest';

import { cancelBacktest, createBacktest, getBacktest, getBacktests, getEquity, getTrades } from './backtest-apis';

const POLL_MS = 2_000;

export const backtestKeys = {
  all: ['backtests'] as const,
  list: (query: BacktestListQuery = {}) => [...backtestKeys.all, 'list', query] as const,
  detail: (id: string) => [...backtestKeys.all, 'detail', id] as const,
  equity: (id: string) => [...backtestKeys.all, 'equity', id] as const,
  trades: (id: string, offset: number, limit: number) => [...backtestKeys.all, 'trades', id, offset, limit] as const,
};

export function backtestsQueryOptions(query: BacktestListQuery = {}) {
  return queryOptions({
    queryKey: backtestKeys.list(query),
    queryFn: () => getBacktests(query),
    placeholderData: keepPreviousData, // No flash of skeleton between pages.
    refetchInterval: ({ state }) => (state.data?.data.some((r) => !isTerminal(r.status)) ? POLL_MS : false),
  });
}

// Polls every 2s until the run finishes, then stops for good.
export function backtestQueryOptions(id: string) {
  return queryOptions({
    queryKey: backtestKeys.detail(id),
    queryFn: () => getBacktest(id),
    refetchInterval: ({ state }) => (state.data && isTerminal(state.data.status) ? false : POLL_MS),
  });
}

// A finished run's series never change.
export function equityQueryOptions(id: string, enabled: boolean) {
  return queryOptions({
    queryKey: backtestKeys.equity(id),
    queryFn: () => getEquity(id),
    enabled,
    staleTime: Infinity,
  });
}

export function tradesQueryOptions(id: string, offset: number, limit: number, enabled: boolean) {
  return queryOptions({
    queryKey: backtestKeys.trades(id, offset, limit),
    queryFn: () => getTrades(id, { offset, limit }),
    enabled,
    staleTime: Infinity,
    placeholderData: keepPreviousData,
  });
}

export function createBacktestMutationOptions(client: QueryClient) {
  return mutationOptions({
    mutationKey: [...backtestKeys.all, 'create'],
    mutationFn: createBacktest,
    onSuccess: (run) => {
      client.setQueryData(backtestKeys.detail(run.id), run);
      void client.invalidateQueries({ queryKey: [...backtestKeys.all, 'list'] });
    },
  });
}

export function cancelBacktestMutationOptions(client: QueryClient) {
  return mutationOptions({
    mutationKey: [...backtestKeys.all, 'cancel'],
    mutationFn: cancelBacktest,
    onSuccess: (run) => {
      client.setQueryData(backtestKeys.detail(run.id), run);
      void client.invalidateQueries({ queryKey: [...backtestKeys.all, 'list'] });
    },
  });
}
