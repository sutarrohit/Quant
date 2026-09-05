import { handleResponse } from './handleResponse';
import env from '../env';

const API_BASE = `${env.NEXT_PUBLIC_API_URL}/api/v1`;

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });

  return handleResponse(res);
}
