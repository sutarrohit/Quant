import { describe, expect, it } from 'vitest';

import { lttb } from '../../src/lib/downsample.js';

const series = (n: number) => Array.from({ length: n }, (_, i) => ({ i, v: Math.sin(i / 50) * 100 }));

describe('lttb', () => {
  it('returns short series untouched', () => {
    const points = series(10);
    expect(lttb(points, 1_000, (p) => p.v)).toBe(points);
  });

  it('thins to the threshold and keeps both ends', () => {
    const points = series(50_000);
    const out = lttb(points, 1_000, (p) => p.v);

    expect(out).toHaveLength(1_000);
    expect(out[0]).toBe(points[0]);
    expect(out.at(-1)).toBe(points.at(-1));
  });

  it('keeps a lone spike a stride would drop', () => {
    const points = series(10_000).map((p) => ({ ...p, v: 0 }));
    points[5_003] = { i: 5_003, v: -500 };

    expect(lttb(points, 100, (p) => p.v)).toContain(points[5_003]);
  });

  it('keeps points in order', () => {
    const out = lttb(series(20_000), 500, (p) => p.v);
    expect(out.every((p, k) => k === 0 || p.i > out[k - 1]!.i)).toBe(true);
  });
});
