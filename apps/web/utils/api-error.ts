import type { ApiErrorBody } from '@quant/contracts/error';
import type { SpecError } from '@quant/contracts/strategy';

/** A failed API call, keeping what the server said -- clients branch on `code`, never on message. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string | undefined; // Quote it to trace the call through Hono and the engine.

  constructor(status: number, body: Partial<ApiErrorBody>, requestId?: string) {
    super(body.message ?? 'API request failed');
    this.name = 'ApiError';
    this.status = status;
    this.code = body.code ?? 'UNKNOWN';
    this.details = body.details;
    this.requestId = body.requestId ?? requestId; // The header covers a body that never parsed.
  }

  /** The per-field problems from a rejected spec, or none. */
  get specErrors(): SpecError[] {
    return this.code === 'SPEC_INVALID' && Array.isArray(this.details) ? (this.details as SpecError[]) : [];
  }
}
