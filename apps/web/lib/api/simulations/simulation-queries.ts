import { keepPreviousData, mutationOptions, queryOptions, type QueryClient } from '@tanstack/react-query';
import type {
  Simulation,
  SimulationEquity,
  SimulationEventPage,
  StartSimulationInput,
} from '@quant/contracts/simulation';

import { ApiError } from '@/utils/api-error';

import {
  createSimulation,
  engageKill,
  getSimulation,
  getSimulationEquity,
  getSimulationEvents,
  getSimulationFills,
  getSimulationSnapshot,
  getSimulations,
  releaseKill,
  startSimulation,
  stopSimulation,
} from './simulation-apis';

// 5s, and only while the tab is visible -- TanStack's default for refetchInterval.
const POLL_MS = 5_000;

// Only once loaded: polling a first load that is still retrying restarts the retries, and it never fails.
const pollOnceLoaded = ({ state }: { state: { data: unknown } }) => (state.data ? POLL_MS : false);

export const simulationKeys = {
  all: ['simulations'] as const,
  list: () => [...simulationKeys.all, 'list'] as const,
  detail: (id: string) => [...simulationKeys.all, 'detail', id] as const,
  snapshot: (id: string) => [...simulationKeys.all, 'snapshot', id] as const,
  events: (id: string) => [...simulationKeys.all, 'events', id] as const,
  equity: (id: string) => [...simulationKeys.all, 'equity', id] as const,
  fills: (id: string, page: number, pageSize: number) => [...simulationKeys.all, 'fills', id, page, pageSize] as const,
};

/** The node has not published yet: seconds after a start. Worth polling through. */
export const isStarting = (error: unknown) => error instanceof ApiError && error.code === 'SNAPSHOT_NOT_FOUND';

const EVENTS_KEPT = 500; // The feed shows recent activity; the engine keeps ~1,000.

export function simulationsQueryOptions() {
  return queryOptions({ queryKey: simulationKeys.list(), queryFn: getSimulations, refetchInterval: pollOnceLoaded });
}

// A simulation is never "finished", so the poll never stops by itself.
export function simulationQueryOptions(id: string) {
  return queryOptions({
    queryKey: simulationKeys.detail(id),
    queryFn: () => getSimulation(id),
    refetchInterval: pollOnceLoaded,
  });
}

export function simulationSnapshotQueryOptions(id: string) {
  return queryOptions({
    queryKey: simulationKeys.snapshot(id),
    queryFn: () => getSimulationSnapshot(id),
    refetchInterval: ({ state }) => (state.data || isStarting(state.error) ? POLL_MS : false),
  });
}

// Incremental: each poll asks only for what came after the cached page's cursor.
export function simulationEventsQueryOptions(client: QueryClient, id: string) {
  const queryKey = simulationKeys.events(id);
  return queryOptions({
    queryKey,
    queryFn: async (): Promise<SimulationEventPage> => {
      const cached = client.getQueryData<SimulationEventPage>(queryKey);
      const page = await getSimulationEvents(id, cached?.last ?? undefined, cached ? 1_000 : 200);
      if (!cached) return page;
      return { events: [...cached.events, ...page.events].slice(-EVENTS_KEPT), last: page.last ?? cached.last };
    },
    refetchInterval: pollOnceLoaded,
  });
}

export function simulationEquityQueryOptions(client: QueryClient, id: string) {
  const queryKey = simulationKeys.equity(id);
  return queryOptions({
    queryKey,
    queryFn: async (): Promise<SimulationEquity> => {
      const cached = client.getQueryData<SimulationEquity>(queryKey);
      const page = await getSimulationEquity(id, cached?.last ?? undefined);
      if (!cached) return page;
      return { points: [...cached.points, ...page.points], last: page.last ?? cached.last };
    },
    refetchInterval: pollOnceLoaded,
  });
}

export function simulationFillsQueryOptions(id: string, page: number, pageSize: number) {
  return queryOptions({
    queryKey: simulationKeys.fills(id, page, pageSize),
    queryFn: () => getSimulationFills(id, page, pageSize),
    placeholderData: keepPreviousData, // No flash of skeleton between pages.
    refetchInterval: pollOnceLoaded,
  });
}

// Every action answers with the fresh simulation; write it straight into the cache.
const settle = (client: QueryClient) => (sim: Simulation) => {
  client.setQueryData(simulationKeys.detail(sim.id), sim);
  void client.invalidateQueries({ queryKey: simulationKeys.list() });
};

export function createSimulationMutationOptions(client: QueryClient) {
  return mutationOptions({
    mutationKey: [...simulationKeys.all, 'create'],
    mutationFn: createSimulation,
    onSuccess: settle(client),
  });
}

export function startSimulationMutationOptions(client: QueryClient, id: string) {
  return mutationOptions({
    mutationKey: [...simulationKeys.all, 'start', id],
    mutationFn: (input: StartSimulationInput) => startSimulation(id, input),
    onSuccess: settle(client),
  });
}

export function stopSimulationMutationOptions(client: QueryClient, id: string) {
  return mutationOptions({
    mutationKey: [...simulationKeys.all, 'stop', id],
    mutationFn: () => stopSimulation(id),
    onSuccess: settle(client),
  });
}

export function killMutationOptions(client: QueryClient, id: string) {
  return mutationOptions({
    mutationKey: [...simulationKeys.all, 'kill', id],
    mutationFn: (engage: boolean) => (engage ? engageKill(id) : releaseKill(id)),
    onSuccess: settle(client),
  });
}
