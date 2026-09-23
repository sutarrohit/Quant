import { ApiError } from './api-error';

export const handleResponse = async (response: Response) => {
  if (response.status === 204) return;
  const data = await response.json().catch(() => ({})); // A proxy error page is not JSON.
  if (!response.ok) throw new ApiError(response.status, data ?? {}, response.headers.get('x-request-id') ?? undefined);
  return data;
};
