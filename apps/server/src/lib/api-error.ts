export class ApiError extends Error {
  status: number;
  code: string;
  details?: unknown; // e.g. the engine's spec errors, each tagged with its path.

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}
