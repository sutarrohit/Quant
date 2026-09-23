import { mutationOptions, queryOptions, type QueryClient } from '@tanstack/react-query';
import type { Simulation, StartSimulationInput } from '@quant/contracts/simulation';

import {
  createSimulation,
  engageKill,
  getSimulation,
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
};

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
