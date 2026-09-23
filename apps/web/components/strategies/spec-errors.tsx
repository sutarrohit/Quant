'use client';

import { createContext, useContext } from 'react';

import { toFieldPath } from '@/lib/strategies/tree';

// Semantic and server errors, keyed by form path, so each node reads its own.
const SpecErrorsContext = createContext<Map<string, string[]>>(new Map());

export const SpecErrorsProvider = SpecErrorsContext.Provider;

export function buildErrorMap(errors: { path: string; message: string }[]): Map<string, string[]> {
  const map = new Map<string, string[]>();
  for (const { path, message } of errors) {
    const key = toFieldPath(path);
    map.set(key, [...(map.get(key) ?? []), message]);
  }
  return map;
}

export const useErrorMap = () => useContext(SpecErrorsContext);
export const useErrorsAt = (path: string): string[] => useErrorMap().get(path) ?? [];

export function ErrorList({ messages }: { messages: string[] }) {
  if (messages.length === 0) return null;
  return (
    <ul className="flex flex-col gap-0.5 text-xs text-destructive">
      {[...new Set(messages)].map((m) => (
        <li key={m}>{m}</li>
      ))}
    </ul>
  );
}
