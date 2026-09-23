'use client';

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

/** A compact select over a fixed `value -> label` map. */
export function Choice({
  value,
  onChange,
  options,
  label,
  invalid,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  options: Record<string, string>;
  label: string; // Accessible name; rows of selects have no visible label.
  invalid?: boolean;
  className?: string;
}) {
  return (
    <Select value={value} onValueChange={(v) => v !== null && onChange(String(v))} items={options}>
      <SelectTrigger size="sm" aria-label={label} aria-invalid={invalid || undefined} className={className}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {Object.entries(options).map(([v, text]) => (
          <SelectItem key={v} value={v}>
            {text}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
