import type { CSSProperties } from 'react';

// Grid cell is 48px; each beam sits on a grid line (index * 48px) so it runs along it.
const CELL = 48;
const VERTICAL = [
  { line: 4, duration: 6, delay: 0 },
  { line: 9, duration: 8, delay: 2.5 },
  { line: 17, duration: 7, delay: 1.2 },
  { line: 24, duration: 9, delay: 4 },
  { line: 30, duration: 6.5, delay: 3 },
];
const HORIZONTAL = [
  { line: 2, duration: 9, delay: 1 },
  { line: 5, duration: 11, delay: 5 },
  { line: 8, duration: 10, delay: 2.8 },
];

export function GridBeams() {
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0 -z-10 overflow-hidden [mask-image:radial-gradient(ellipse_at_top,black_30%,transparent_75%)]"
    >
      <div className="absolute inset-0 bg-[linear-gradient(to_right,var(--border)_1px,transparent_1px),linear-gradient(to_bottom,var(--border)_1px,transparent_1px)] bg-[size:48px_48px]" />

      {VERTICAL.map((b) => (
        <div key={`v${b.line}`} className="absolute top-0 h-full w-px" style={{ left: b.line * CELL }}>
          <div
            className="animate-beam-y h-24 w-px bg-gradient-to-b from-transparent via-emerald-400 to-transparent"
            style={{ '--beam-duration': `${b.duration}s`, '--beam-delay': `${b.delay}s` } as CSSProperties}
          />
        </div>
      ))}

      {HORIZONTAL.map((b) => (
        <div key={`h${b.line}`} className="absolute left-0 h-px w-full" style={{ top: b.line * CELL }}>
          <div
            className="animate-beam-x h-px w-32 bg-gradient-to-r from-transparent via-cyan-400 to-transparent"
            style={{ '--beam-duration': `${b.duration}s`, '--beam-delay': `${b.delay}s` } as CSSProperties}
          />
        </div>
      ))}
    </div>
  );
}
