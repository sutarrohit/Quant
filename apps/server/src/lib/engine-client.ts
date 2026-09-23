import { getContext } from 'hono/context-storage';

import env from '../env.js';
import type { AppBinding } from '../types/app.js';
import type { EngineRefusal, EngineRequest } from '../types/engine.js';
import { ApiError } from './api-error.js';

/**
 * The only module that knows the engine's address or holds its token.
 *
 * `path` is always a literal written here, never a value from a request -- the
 * engine trusts its caller completely, because we are its only one.
 */

const TIMEOUT_MS = 15_000;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const toCamel = (key: string) => key.replace(/_([a-z0-9])/g, (_, c: string) => c.toUpperCase());

/**
 * Rewrite snake_case keys to camelCase, recursively.
 *
 * The engine takes camelCase but answers in snake_case, so the seam is closed
 * here rather than in every handler and component. Already-camelCase keys pass
 * through untouched -- a response can hold both spellings at once.
 *
 * Keys only. Values are untouched: money is a decimal string and stays one.
 */
export function camelize<T>(value: unknown): T {
  if (Array.isArray(value)) return value.map((item) => camelize(item)) as T;
  if (!isRecord(value)) return value as T;

  const out: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) out[toCamel(key)] = camelize(item);
  return out as T;
}

/**
 * Turn an engine failure into one of ours.
 *
 * 401/403 never passes through: the engine rejecting our token is our
 * misconfiguration, and forwarding it would bounce a signed-in user to login.
 * A 422 keeps its list, so the builder can mark every bad field at once.
 */
function refusal(status: number, body: EngineRefusal): ApiError {
  if (status === 401 || status === 403) {
    return new ApiError(502, 'ENGINE_UNAUTHORIZED', 'the engine rejected this service’s credentials');
  }

  if (Array.isArray(body.errors)) {
    return new ApiError(422, 'SPEC_INVALID', 'the strategy spec is not runnable', body.errors);
  }

  return new ApiError(
    status,
    body.code ?? 'ENGINE_ERROR',
    body.message ?? 'the engine refused the request',
    body.details
  );
}

/** The current request's id, so the engine logs under the same one. Absent outside a request. */
function currentRequestId(): string | undefined {
  try {
    return getContext<AppBinding>().var.requestId;
  } catch {
    return undefined;
  }
}

/** Call the engine and return its answer with camelCase keys. */
export async function engineFetch<T>(path: string, options: EngineRequest = {}): Promise<T> {
  const { method = 'GET', body, query } = options;
  const requestId = options.requestId ?? currentRequestId();

  const url = new URL(`${env.ENGINE_URL.replace(/\/$/, '')}${path}`);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) url.searchParams.set(key, String(value));
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers: {
        Authorization: `Bearer ${env.ENGINE_INTERNAL_API_KEY}`,
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...(requestId === undefined ? {} : { 'x-request-id': requestId }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (cause) {
    // 502, not 500: the failure is upstream and the request is worth retrying.
    throw new ApiError(502, 'ENGINE_UNAVAILABLE', 'could not reach the engine service', {
      cause: cause instanceof Error ? cause.name : 'unknown',
    });
  }

  if (response.status === 204) return undefined as T; // No body to parse.

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    // Unparseable body -- an engine defect, or an HTML page from a proxy.
    if (response.ok) {
      throw new ApiError(502, 'ENGINE_RESPONSE_INVALID', 'the engine returned an unreadable body');
    }
    throw new ApiError(502, 'ENGINE_ERROR', `the engine returned ${response.status}`);
  }

  if (!response.ok) throw refusal(response.status, (payload ?? {}) as EngineRefusal);

  return camelize<T>(payload);
}
