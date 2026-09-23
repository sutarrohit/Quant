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

/** `POST /v1/backtests` — 202 for a new job, 200 for a replay. Both are success. */
export interface EngineSubmitted {
  jobId: string;
  status: string;
}

/** `GET /v1/backtests/{jobId}`. */
export interface EngineJob {
  jobId: string;
  status: string;
  submittedAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  error: { code: string; message: string } | null;
  result: { summary?: Record<string, unknown> } | null;
}

/** One page of an artifact series. */
export interface EngineSeriesPage<T> {
  rows: T[];
  total: number;
  offset: number;
  limit: number;
}

/** `GET /v1/live/{accountId}`, camelized. Desired is ours to set; observed is the supervisor's report. */
export interface EngineLiveState {
  desired: {
    status: 'RUNNING' | 'STOPPED';
    revision: number;
    specHash: string;
    strategyVersionId: string;
    updatedAt: string;
  };
  observed: {
    status: 'STARTING' | 'RECONCILING' | 'RUNNING' | 'STOPPED' | 'FAILED' | 'HALTED';
    revision: number;
    startedAt: string | null;
    heartbeatAt: string | null;
    error: Record<string, unknown> | null;
  } | null;
  leaseHolder: string | null;
}

/** `GET|POST|DELETE /v1/live/{accountId}/kill`. */
export interface EngineKill {
  accountId: string;
  killSwitch: 'ENGAGED' | 'RELEASED';
}
