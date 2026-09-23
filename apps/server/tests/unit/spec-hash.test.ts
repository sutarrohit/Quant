import { describe, expect, it } from 'vitest';

import { specHash } from '@quant/contracts/spec-hash';

describe('specHash', () => {
  it('ignores key order at every depth', () => {
    // Two specs differing only in key order are the same strategy. If they
    // hashed differently, the version history would report an edit that never
    // happened -- and addVersion would write a duplicate row.
    const a = { strategyId: 'x', market: { exchange: 'binance', symbols: ['SOL/USDT'] } };
    const b = { market: { symbols: ['SOL/USDT'], exchange: 'binance' }, strategyId: 'x' };

    expect(specHash(a)).toBe(specHash(b));
  });

  it('does not ignore array order', () => {
    // `all: [a, b]` and `all: [b, a]` evaluate the same, but the engine hashes
    // the spec as written, and reordering is an edit a user made.
    expect(specHash({ all: [1, 2] })).not.toBe(specHash({ all: [2, 1] }));
  });

  it('separates a changed value', () => {
    expect(specHash({ riskPercent: '1' })).not.toBe(specHash({ riskPercent: '2' }));
  });

  it('separates a string from the number that looks like it', () => {
    // Money is a string end to end; "1" and 1 are different specs.
    expect(specHash({ v: '1' })).not.toBe(specHash({ v: 1 }));
  });
});
