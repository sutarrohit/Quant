'use client';

import { useState } from 'react';

import { Input } from '@/components/ui/input';

/**
 * Comma-separated symbols, e.g. "SOL/USDT, ETH/USDT".
 *
 * Keeps its own text: deriving it from the array would eat a trailing comma
 * and make a second symbol impossible to type.
 */
export function SymbolsInput({
  value,
  onChange,
  ...props
}: { value: string[]; onChange: (symbols: string[]) => void } & Omit<React.ComponentProps<typeof Input>, 'value' | 'onChange'>) {
  const [text, setText] = useState(value.join(', '));

  return (
    <Input
      {...props}
      value={text}
      placeholder="SOL/USDT, ETH/USDT"
      onChange={(e) => {
        setText(e.target.value);
        onChange(
          e.target.value
            .split(',')
            .map((s) => s.trim().toUpperCase())
            .filter(Boolean)
        );
      }}
    />
  );
}
