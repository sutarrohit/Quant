import { toast } from 'sonner';

import { ApiError } from './api-error';

/** An error toast carrying the request id, so a screenshot of it can be traced. */
export function toastError(error: unknown, fallback = 'Something went wrong') {
  const message = error instanceof Error ? error.message : fallback;
  const ref = error instanceof ApiError ? error.requestId : undefined;
  toast.error(message, ref ? { description: `Ref: ${ref}` } : undefined);
}
