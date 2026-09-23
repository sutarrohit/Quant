import { extendZodWithOpenApi } from '@asteasolutions/zod-to-openapi';
import { z } from 'zod';

import { shape } from './spec-tree.js';

// Adds `.openapi()` to the shared zod instance. Needed here rather than in
// apps/server because ConditionNodeSchema has to carry the metadata itself --
// it is nested inside StrategySpecSchema, and registering a copy later would
// not reach the instance the route actually serialises.
extendZodWithOpenApi(z);

// The strategy spec, mirroring engine/types/dsl.py field for field. The engine
// is authoritative and validates again -- this exists so the builder can reject
// a bad spec without a round trip, and so the stored JSON is known-good.

export const INDICATORS = ['rsi', 'sma', 'ema', 'atr', 'close', 'volume'] as const;
export const OPERATORS = [
  'crossesAbove',
  'crossesBelow',
  'greaterThan',
  'lessThan',
  'greaterThanSma',
  'lessThanSma',
] as const;

// Volume is spiky rather than continuous, so a "crossing" of it means nothing;
// comparison against its own average does. Everything else gets the four.
const SERIES_OPERATORS = ['crossesAbove', 'crossesBelow', 'greaterThan', 'lessThan'] as const;
const VOLUME_OPERATORS = ['greaterThan', 'lessThan', 'greaterThanSma', 'lessThanSma'] as const;

export const OPERATORS_BY_INDICATOR: Record<string, readonly string[]> = {
  rsi: SERIES_OPERATORS,
  sma: SERIES_OPERATORS,
  ema: SERIES_OPERATORS,
  atr: SERIES_OPERATORS,
  close: SERIES_OPERATORS,
  volume: VOLUME_OPERATORS,
};

/** Indicators that need a period, and those that cannot take one. */
export const PERIODIC = new Set(['rsi', 'sma', 'ema', 'atr']);
export const BAR_DERIVED = new Set(['close', 'volume']);
export const SMA_OPERATORS = new Set(['greaterThanSma', 'lessThanSma']);

export const MAX_DEPTH = 5;
export const MAX_LEAVES = 32;

const DECIMAL = /^-?\d+(\.\d+)?$/;

/**
 * A money-shaped value, kept as a string.
 *
 * A number in, a string out: JSON floats do not round-trip exactly, and the spec
 * is hashed into an identity that must keep meaning the same thing. The engine
 * parses these as Decimal either way.
 */
const decimal = (opts: { gt?: number; gte?: number; lt?: number; lte?: number }) =>
  z
    .union([z.string(), z.number()])
    .transform((v) => String(v))
    .refine((v) => DECIMAL.test(v), { message: 'must be a decimal number' })
    .refine((v) => (opts.gt === undefined ? true : Number(v) > opts.gt), {
      message: `must be greater than ${opts.gt}`,
    })
    .refine((v) => (opts.gte === undefined ? true : Number(v) >= opts.gte), {
      message: `must be at least ${opts.gte}`,
    })
    .refine((v) => (opts.lt === undefined ? true : Number(v) < opts.lt), {
      message: `must be less than ${opts.lt}`,
    })
    .refine((v) => (opts.lte === undefined ? true : Number(v) <= opts.lte), {
      message: `must be at most ${opts.lte}`,
    });

const period = z.number().int().min(2).max(1000);

export const MarketSchema = z.object({
  exchange: z.literal('binance'), // The only one the engine implements.
  marketType: z.literal('spot'),
  symbols: z.array(z.string().min(1)).min(1).max(8), // Written the human way: "SOL/USDT".
  timeframe: z.enum(['1m', '5m', '15m', '1h', '4h', '1d']),
});

// Another series to compare against, instead of a fixed number. This is what
// makes the crossover family expressible.
export const SeriesReferenceSchema = z.object({
  indicator: z.enum(INDICATORS),
  period: period.optional(),
});

export const IndicatorConditionSchema = z.object({
  indicator: z.enum(INDICATORS),
  operator: z.enum(OPERATORS),
  period: period.optional(),
  value: decimal({}).optional(), // Mutually exclusive with `reference`.
  reference: SeriesReferenceSchema.optional(),
});

export const ExitConditionSchema = z.discriminatedUnion('type', [
  z.object({ type: z.literal('takeProfitPercent'), value: decimal({ gt: 0, lte: 1000 }) }),
  z.object({ type: z.literal('stopLossPercent'), value: decimal({ gt: 0, lt: 100 }) }),
]);

// `entry` and `exit` are each one node: a group, an indicator leaf, or an exit
// leaf. Groups nest, so the type is recursive and Zod needs the lazy hand-off.
export type ConditionNode =
  | { all: ConditionNode[] }
  | { any: ConditionNode[] }
  | { not: ConditionNode }
  | z.infer<typeof IndicatorConditionSchema>
  | z.infer<typeof ExitConditionSchema>;

// Named, so OpenAPI emits a $ref. A recursive schema cannot be inlined, and
// without this the whole document generates empty -- measured, not assumed.
export const ConditionNodeSchema: z.ZodType<ConditionNode> = z
  .lazy(() =>
    z.union([
      z.object({ all: z.array(ConditionNodeSchema) }),
      z.object({ any: z.array(ConditionNodeSchema) }),
      z.object({ not: ConditionNodeSchema }),
      IndicatorConditionSchema,
      ExitConditionSchema,
    ])
  )
  .openapi('ConditionNode');

export const SizingSchema = z.object({
  type: z.literal('riskPercent'), // The only one implemented.
  riskPercent: decimal({ gt: 0, lte: 100 }),
});

export const StrategySpecSchema = z
  .object({
    strategyId: z
      .string()
      .min(1)
      .max(128)
      .regex(/^[a-zA-Z0-9][a-zA-Z0-9._-]*$/),
    version: z.number().int().min(1),
    market: MarketSchema,
    entry: ConditionNodeSchema,
    exit: ConditionNodeSchema,
    sizing: SizingSchema,
  })
  // Bounds what the interpreter must evaluate, and stops a pathological
  // generated spec. A schema error here, exactly as on the engine -- so the
  // SpecError codes stay the set the engine can actually send.
  .superRefine((spec, ctx) => {
    for (const name of ['entry', 'exit'] as const) {
      const { depth, leaves } = shape(spec[name]);
      if (depth > MAX_DEPTH) {
        ctx.addIssue({
          code: 'custom',
          path: [name],
          message: `nests ${depth} levels deep; the limit is ${MAX_DEPTH}`,
        });
      }
      if (leaves > MAX_LEAVES) {
        ctx.addIssue({
          code: 'custom',
          path: [name],
          message: `has ${leaves} conditions; the limit is ${MAX_LEAVES}`,
        });
      }
    }
  });

export type StrategySpec = z.infer<typeof StrategySpecSchema>;
export type StrategySpecInput = z.input<typeof StrategySpecSchema>; // What a form holds: money may still be a number.
export type Market = z.infer<typeof MarketSchema>;
export type IndicatorCondition = z.input<typeof IndicatorConditionSchema>;
export type ExitCondition = z.input<typeof ExitConditionSchema>;
