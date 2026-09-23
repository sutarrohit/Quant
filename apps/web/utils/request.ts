import { getAccessToken } from '@privy-io/react-auth';

import { handleResponse } from './handleResponse';

// Relative: the rewrite in next.config.ts proxies these, keeping the cookie
// same-origin so it is always sent and never needs CORS.
const API_BASE = '/api/v1';

// Belt and braces alongside the cookie: on Privy's default localStorage storage
// there is no cookie, and this header is the only thing carrying the token.
// Wrapped because it throws during SSR and before Privy rehydrates.
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
    credentials: 'include', // The default now, but the auth scheme depends on it.
    // Spread last, so a caller's `headers` add to these rather than replace them.
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    },
  });

  return handleResponse(res);
}
