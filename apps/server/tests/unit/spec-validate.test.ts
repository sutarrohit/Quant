import { describe, expect, it } from 'vitest';

import { validateSpec } from '../../src/lib/spec-validate.js';
import { StrategySpecSchema, type StrategySpec } from '../../src/types/spec.js';

// A spec that passes every rule, so each test can break exactly one thing.
const VALID = {
  strategyId: 'sma-cross',
  version: 1,
  market: { exchange: 'binance', marketType: 'spot', symbols: ['SOL/USDT'], timeframe: '15m' },
  entry: { indicator: 'close', operator: 'crossesAbove', reference: { indicator: 'sma', period: 200 } },
  exit: { any: [{ type: 'stopLossPercent', value: 2 }, { type: 'takeProfitPercent', value: 4 }] },
  sizing: { type: 'riskPercent', riskPercent: 1 },
};

const parse = (spec: unknown): StrategySpec => {
  const result = StrategySpecSchema.safeParse(spec);
  if (!result.success) throw new Error(`fixture does not parse: ${result.error.message}`);
  return result.data;
};

const codes = (spec: unknown) => validateSpec(parse(spec)).map((e) => e.code);
const edit = (patch: Record<string, unknown>) => ({ ...VALID, ...patch });

describe('a runnable spec', () => {
  it('has nothing to report', () => {
    expect(validateSpec(parse(VALID))).toEqual([]);
  });

  it('keeps money as a string so the decimal survives', () => {
    // A JSON float does not round-trip exactly, and the spec is hashed into an
    // identity that has to keep meaning the same thing.
    const spec = parse(VALID);
    expect(spec.sizing.riskPercent).toBe('1');
    expect(typeof spec.sizing.riskPercent).toBe('string');
  });
});

describe('sizing needs something to divide by', () => {
  it('rejects riskPercent with no stop loss', () => {
    // Size = (equity x riskPercent) / stop distance.
    const spec = edit({ exit: { type: 'takeProfitPercent', value: 4 } });
    expect(codes(spec)).toContain('MISSING_STOP_LOSS');
  });

  it('accepts a stop nested inside a group', () => {
    const spec = edit({
      exit: { any: [{ not: { type: 'stopLossPercent', value: 2 } }] },
    });
    expect(codes(spec)).not.toContain('MISSING_STOP_LOSS');
  });
});

describe('operators are per indicator', () => {
  it('refuses a crossing on volume', () => {
    // Volume is spiky rather than continuous, so a crossing means nothing.
    const spec = edit({
      entry: { indicator: 'volume', operator: 'crossesAbove', value: 1000 },
    });
    expect(codes(spec)).toContain('UNSUPPORTED_OPERATOR');
  });

  it('allows volume against its own average', () => {
    const spec = edit({
      entry: { indicator: 'volume', operator: 'greaterThanSma', period: 20 },
    });
    expect(codes(spec)).not.toContain('UNSUPPORTED_OPERATOR');
  });
});

describe('periods', () => {
  it('requires one on rsi', () => {
    const spec = edit({ entry: { indicator: 'rsi', operator: 'greaterThan', value: 30 } });
    expect(codes(spec)).toContain('MISSING_PERIOD');
  });

  it('refuses one on close', () => {
    const spec = edit({
      entry: { indicator: 'close', operator: 'greaterThan', value: 1, period: 14 },
    });
    expect(codes(spec)).toContain('INVALID_REFERENCE');
  });

  it('requires one on volume only for the averaging operators', () => {
    expect(
      codes(edit({ entry: { indicator: 'volume', operator: 'greaterThanSma' } }))
    ).toContain('MISSING_PERIOD');
    expect(
      codes(edit({ entry: { indicator: 'volume', operator: 'greaterThan', value: 1, period: 20 } }))
    ).toContain('INVALID_REFERENCE');
  });
});

describe('exactly one of value or reference', () => {
  it('refuses neither', () => {
    const spec = edit({ entry: { indicator: 'rsi', period: 14, operator: 'greaterThan' } });
    expect(codes(spec)).toContain('MISSING_THRESHOLD');
  });

  it('refuses both', () => {
    const spec = edit({
      entry: {
        indicator: 'rsi',
        period: 14,
        operator: 'greaterThan',
        value: 30,
        reference: { indicator: 'sma', period: 50 },
      },
    });
    expect(codes(spec)).toContain('AMBIGUOUS_COMPARISON');
  });

  it('refuses a reference alongside an averaging operator', () => {
    // greaterThanSma already compares against an average.
    const spec = edit({
      entry: {
        indicator: 'volume',
        operator: 'greaterThanSma',
        period: 20,
        reference: { indicator: 'sma', period: 50 },
      },
    });
    expect(codes(spec)).toContain('AMBIGUOUS_COMPARISON');
  });
});

describe('references', () => {
  it('refuses sma with no period', () => {
    const spec = edit({
      entry: { indicator: 'close', operator: 'greaterThan', reference: { indicator: 'sma' } },
    });
    expect(codes(spec)).toContain('INVALID_REFERENCE');
  });

  it('refuses close with one', () => {
    const spec = edit({
      entry: {
        indicator: 'rsi',
        period: 14,
        operator: 'greaterThan',
        reference: { indicator: 'close', period: 20 },
      },
    });
    expect(codes(spec)).toContain('INVALID_REFERENCE');
  });
});

describe('groups', () => {
  it('refuses an empty one', () => {
    // `all` of nothing is true, so it fires on every bar.
    expect(codes(edit({ entry: { all: [] } }))).toContain('EMPTY_CONDITION_GROUP');
  });

  it('refuses the same condition stated twice', () => {
    const leaf = { indicator: 'rsi', period: 14, operator: 'greaterThan', value: 30 };
    expect(codes(edit({ entry: { all: [leaf, leaf] } }))).toContain('DUPLICATE_CONDITION');
  });
});

describe('exit conditions belong in exit', () => {
  it('refuses a stop loss in entry', () => {
    // There is no position yet to measure against.
    const spec = edit({ entry: { all: [{ type: 'stopLossPercent', value: 2 }] } });
    expect(codes(spec)).toContain('EXIT_CONDITION_IN_ENTRY');
  });
});

describe('every problem is reported, not the first', () => {
  it('returns a list the builder can mark in one pass', () => {
    const spec = edit({
      entry: { all: [{ indicator: 'rsi', operator: 'greaterThan' }] },
      exit: { type: 'takeProfitPercent', value: 4 },
    });
    const errors = validateSpec(parse(spec));

    expect(errors.length).toBeGreaterThan(2);
    expect(errors.map((e) => e.code)).toEqual(
      expect.arrayContaining(['MISSING_PERIOD', 'MISSING_THRESHOLD', 'MISSING_STOP_LOSS'])
    );
    // Each carries the path it sits on.
    expect(errors.every((e) => e.path.length > 0)).toBe(true);
  });
});

describe('the schema bounds the tree', () => {
  it('refuses more than five levels', () => {
    let node: unknown = { indicator: 'rsi', period: 14, operator: 'greaterThan', value: 30 };
    for (let i = 0; i < 6; i += 1) node = { all: [node] };
    expect(StrategySpecSchema.safeParse(edit({ entry: node })).success).toBe(false);
  });
});
