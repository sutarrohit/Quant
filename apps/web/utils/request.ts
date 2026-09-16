import { handleResponse } from './handleResponse';

// Relative, not absolute: requests go to this app's own origin and are proxied
// to the API by the rewrite in next.config.ts. That keeps the privy-token cookie
// same-origin, so it is always sent and never needs CORS.
const API_BASE = '/api/v1';

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    // Same-origin now, so this is the default -- kept explicit because the whole
    // auth scheme depends on the cookie riding along.
    credentials: 'include',
    // Spread last so a caller passing `headers` adds to these rather than
    // replacing them.
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  return handleResponse(res);
}
