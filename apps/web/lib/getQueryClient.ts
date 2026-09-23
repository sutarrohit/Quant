import { QueryClient, defaultShouldDehydrateQuery } from "@tanstack/react-query";
import { environmentManager } from "@tanstack/react-query";

import { ApiError } from "@/utils/api-error";

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60 * 1000,
        // A 4xx will not change on retry, so it shows at once; a 5xx or network failure gets two quick retries.
        retry: (failures, error) => !(error instanceof ApiError && error.status < 500) && failures < 2,
        retryDelay: (attempt) => 500 * 2 ** attempt,
      },
      dehydrate: {
        // include pending queries in dehydration
        shouldDehydrateQuery: (query) => defaultShouldDehydrateQuery(query) || query.state.status === "pending"
      }
    }
  });
}

let browserQueryClient: QueryClient | undefined = undefined;

export function getQueryClient() {
  if (environmentManager.isServer()) {
    // Server: always make a new query client
    return makeQueryClient();
  } else {
    // Browser: make a new query client if we don't already have one
    // This is very important, so we do`n't re-make a new client if React
    // suspends during the initial render. This may not be needed if we
    // have a suspense boundary BELOW the creation of the query client
    if (!browserQueryClient) browserQueryClient = makeQueryClient();
    return browserQueryClient;
  }
}
