import type {
  CreateStrategyInput,
  CreateVersionInput,
  SpecValidation,
  StrategyDetail,
  StrategyList,
  StrategyVersion,
} from '@quant/contracts/strategy';

import { request } from '@/utils/request';

// One function per route in apps/server/src/routes/strategies/.

// GET /api/v1/strategies
export async function getStrategies(): Promise<StrategyList> {
  return request('/strategies', { method: 'GET' });
}

// GET /api/v1/strategies/:id -- with every version, newest first.
export async function getStrategy(id: string): Promise<StrategyDetail> {
  return request(`/strategies/${id}`, { method: 'GET' });
}

// POST /api/v1/strategies. A rejected spec throws ApiError with `specErrors`.
export async function createStrategy(input: CreateStrategyInput): Promise<StrategyDetail> {
  return request('/strategies', { method: 'POST', body: JSON.stringify(input) });
}

// POST /api/v1/strategies/:id/versions. An unchanged spec returns the current head.
export async function createVersion(id: string, input: CreateVersionInput): Promise<StrategyVersion> {
  return request(`/strategies/${id}/versions`, { method: 'POST', body: JSON.stringify(input) });
}

// DELETE /api/v1/strategies/:id -- a soft delete; versions stay readable.
export async function archiveStrategy(id: string): Promise<void> {
  return request(`/strategies/${id}`, { method: 'DELETE' });
}

// POST /api/v1/strategies/validate. Answers 200 with the problems, so it never throws on a bad spec.
// `unknown`, since the builder sends half-finished drafts.
export async function validateSpec(spec: unknown): Promise<SpecValidation> {
  return request('/strategies/validate', { method: 'POST', body: JSON.stringify({ spec }) });
}
