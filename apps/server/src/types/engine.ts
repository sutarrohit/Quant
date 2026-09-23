// Types for the engine client. Response shapes are declared at each call site,
// since only the caller knows what it asked for.

/** What the engine sends back when it refuses. */
export interface EngineRefusal {
  code?: string;
  message?: string;
  details?: unknown;
  errors?: unknown[]; // A 422 carries every spec problem, not the first.
}

export interface EngineRequest {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown; // Serialised as JSON. The engine takes camelCase.
  requestId?: string; // Sent as `x-request-id`, so one id traces browser -> Hono -> engine.
  query?: Record<string, string | number | undefined>;
}
