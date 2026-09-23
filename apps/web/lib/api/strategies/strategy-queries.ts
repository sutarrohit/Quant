import { mutationOptions, queryOptions, type QueryClient } from '@tanstack/react-query';
import type { CreateVersionInput } from '@quant/contracts/strategy';

import {
  archiveStrategy,
  createStrategy,
  createVersion,
  getStrategies,
  getStrategy,
  validateSpec,
} from './strategy-apis';

// Keys in one place, so an invalidation cannot miss a spelling.
export const strategyKeys = {
  all: ['strategies'] as const,
  list: () => [...strategyKeys.all, 'list'] as const,
  detail: (id: string) => [...strategyKeys.all, 'detail', id] as const,
};

export function strategiesQueryOptions() {
  return queryOptions({ queryKey: strategyKeys.list(), queryFn: getStrategies });
}

export function strategyQueryOptions(id: string) {
  return queryOptions({ queryKey: strategyKeys.detail(id), queryFn: () => getStrategy(id) });
}

export function createStrategyMutationOptions(client: QueryClient) {
  return mutationOptions({
    mutationKey: [...strategyKeys.all, 'create'],
    mutationFn: createStrategy,
    onSuccess: (created) => {
      client.setQueryData(strategyKeys.detail(created.id), created); // The response is the detail view.
      void client.invalidateQueries({ queryKey: strategyKeys.list() });
    },
  });
}

export function createVersionMutationOptions(client: QueryClient, id: string) {
  return mutationOptions({
    mutationKey: [...strategyKeys.all, 'version', id],
    mutationFn: (input: CreateVersionInput) => createVersion(id, input),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: strategyKeys.detail(id) });
      void client.invalidateQueries({ queryKey: strategyKeys.list() });
    },
  });
}

export function archiveStrategyMutationOptions(client: QueryClient) {
  return mutationOptions({
    mutationKey: [...strategyKeys.all, 'archive'],
    mutationFn: archiveStrategy,
    onSuccess: (_, id) => {
      client.removeQueries({ queryKey: strategyKeys.detail(id) });
      void client.invalidateQueries({ queryKey: strategyKeys.list() });
    },
  });
}

// A mutation, not a query: it is asked on demand with the current draft, and
// caching a verdict per draft would be stale by the next keystroke.
export function validateSpecMutationOptions() {
  return mutationOptions({ mutationKey: [...strategyKeys.all, 'validate'], mutationFn: validateSpec });
}
