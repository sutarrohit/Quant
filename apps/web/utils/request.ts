import { getAccessToken } from '@privy-io/react-auth';

import { handleResponse } from './handleResponse';

// Relative, not absolute: requests go to this app's own origin and are proxied
// to the API by the rewrite in next.config.ts. That keeps the privy-token cookie
// same-origin, so it is always sent and never needs CORS.
const API_BASE = '/api/v1';

// Belt and braces alongside the cookie.
//
// When Privy is configured for cookie storage, `credentials: 'include'` alone is
// enough and this header is redundant. When it is still on the default
// localStorage storage -- which is where a Privy app starts, before cookies are
// enabled in the dashboard -- the cookie does not exist and this header is the
// only thing carrying the token. Sending both means local development works
// without any dashboard setup, and production keeps the HttpOnly cookie path.
//
// Wrapped because this can be reached during SSR or before Privy has
// rehydrated, where it throws rather than returning null.
async function bearerToken(): Promise<string | null> {
  try {
    return await getAccessToken();
  } catch {
    return null;
  }
}

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = await bearerToken();

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    // Same-origin now, so this is the default -- kept explicit because the whole
    // auth scheme depends on the cookie riding along.
    credentials: 'include',
    // Spread last so a caller passing `headers` adds to these rather than
    // replacing them.
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    },
  });

  return handleResponse(res);
}
