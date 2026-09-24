import { z } from 'zod';

import { FeesSchema } from './backtest.js';

// A paper-trading account as apps/server returns it: our row (D1) plus the
// engine's live view. The engine never sees a user; the server maps accountId.

export const DESIRED_STATUSES = ['RUNNING', 'STOPPED'] as const;
export const OBSERVED_STATUSES = ['STARTING', 'RECONCILING', 'RUNNING', 'STOPPED', 'FAILED', 'HALTED'] as const;
export const KILL_STATES = ['ENGAGED', 'RELEASED'] as const;

export const HEARTBEAT_STALE_SECONDS = 90; // The engine's live_heartbeat_timeout_seconds.

const decimal = z.string().regex(/^\d+(\.\d+)?$/, 'a positive decimal string');
const bps = FeesSchema.shape.makerBps;

/** Account-level limits. Absent means unlimited -- a choice, not a default. */
export const RiskLimitsSchema = z.object({
  maxOrderNotional: decimal.optional(),
  maxPositionNotional: decimal.optional(),
  maxOpenPositions: z.number().int().min(1).optional(),
  dailyLossLimit: decimal.optional(),
});

export const CreateSimulationSchema = z.object({
  versionId: z.uuid(),
  name: z.string().trim().min(1).max(200),
  venue: z.literal('BINANCE'),
  instrumentId: z.string().regex(/^[A-Z0-9]+\.[A-Z]+$/, 'e.g. SOLUSDT.BINANCE'),
  barType: z.string().min(1).max(128),
  fees: FeesSchema,
  slippageBps: bps, // Collected beside fees like a backtest; the server moves it inside for the engine.
  risk: RiskLimitsSchema.optional(),
});

/** Start, restart, or move to another version. Restating is also how HALTED is cleared. */
export const StartSimulationSchema = z.object({
  versionId: z.uuid().optional(), // Omitted keeps the current version.
});

export const LiveViewSchema = z.object({
  desired: z.object({
    status: z.enum(DESIRED_STATUSES),
    revision: z.number().int(),
    specHash: z.string(),
    strategyVersionId: z.string(),
    updatedAt: z.string(),
  }),
  observed: z
    .object({
      status: z.enum(OBSERVED_STATUSES),
      revision: z.number().int(),
      startedAt: z.string().nullable(),
      heartbeatAt: z.string().nullable(),
      error: z.record(z.string(), z.unknown()).nullable(),
    })
    .nullable(), // Null until the supervisor first picks the account up.
  leaseHolder: z.string().nullable(),
  killSwitch: z.enum(KILL_STATES),
  converging: z.boolean(), // The node has not caught up with the latest request yet (start, version change or stop).
  heartbeatStale: z.boolean(), // Live, but silent for longer than HEARTBEAT_STALE_SECONDS.
});

const amount = z.string().regex(/^-?\d+(\.\d+)?$/, 'a decimal string');

export const STRATEGY_PHASES = ['WARMING_UP', 'WAITING_FOR_ENTRY', 'IN_POSITION'] as const;

/** The list row's glance: from the snapshot, null until the node first publishes. */
export const SimulationPerformanceSchema = z.object({
  equity: amount.nullable(),
  pnl: amount.nullable(),
  returnPercent: amount.nullable(),
  quoteCurrency: z.string().nullable(),
  position: z.object({ side: z.string(), quantity: amount }).nullable(),
  phase: z.enum(STRATEGY_PHASES).nullable(),
  at: z.string(),
  stale: z.boolean(),
});

export const SimulationSchema = z.object({
  id: z.uuid(),
  name: z.string(),
  accountId: z.string(), // For an operator's on-disk kill file; never accepted back.
  strategyId: z.uuid(),
  strategyName: z.string(),
  versionId: z.uuid(),
  version: z.number().int(),
  venue: z.string(),
  instrumentId: z.string(),
  barType: z.string(),
  fees: FeesSchema,
  slippageBps: z.string(),
  risk: RiskLimitsSchema.nullable(),
  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
  live: LiveViewSchema.nullable(), // Null when the engine has no record or could not be reached.
  liveError: z.object({ code: z.string(), message: z.string() }).nullable(),
  performance: SimulationPerformanceSchema.nullable(), // Null until the node first publishes.
});

export const SimulationListSchema = z.object({ simulations: z.array(SimulationSchema) });

export type DesiredStatus = (typeof DESIRED_STATUSES)[number];
export type ObservedStatus = (typeof OBSERVED_STATUSES)[number];
export type KillState = (typeof KILL_STATES)[number];
export type RiskLimits = z.infer<typeof RiskLimitsSchema>;
export type CreateSimulationInput = z.input<typeof CreateSimulationSchema>;
export type CreateSimulation = z.infer<typeof CreateSimulationSchema>;
export type StartSimulationInput = z.input<typeof StartSimulationSchema>;
export type LiveView = z.infer<typeof LiveViewSchema>;
export type Simulation = z.infer<typeof SimulationSchema>;
export type SimulationList = z.infer<typeof SimulationListSchema>;

// --- what a running account is doing (docs/simulation-state-plan.md) ---------
// Every number is a decimal string (S4). Mode-neutral: live reuses these (L1).


/** A Redis stream id, the cursor for events and equity. Opaque to the browser. */
export const STREAM_ID = /^\d{1,20}-\d{1,20}$/;


export const BalanceSchema = z.object({
  currency: z.string(),
  total: amount,
  free: amount,
  locked: amount,
});

export const PositionSchema = z.object({
  side: z.string(), // LONG in v1.
  quantity: amount,
  avgEntry: amount,
  lastPrice: amount.nullable(),
  unrealizedPnl: amount,
  openedAt: z.string(),
  stopPrice: amount.nullable(),
  takeProfitPrice: amount.nullable(),
});

export const ConditionResultSchema = z.object({
  path: z.string(), // e.g. entry.all[0]
  label: z.string(), // e.g. rsi(14) crossesAbove 30
  passed: z.boolean(),
  series: z.string().nullable(), // Key into `values`; null for take-profit and stop-loss.
});

export const StrategyStatusSchema = z.object({
  phase: z.enum(STRATEGY_PHASES),
  barsSeen: z.number().int(),
  warmupBars: z.number().int(),
  barType: z.string(),
  lastBar: z.object({ time: z.string(), close: amount }).nullable(),
  values: z.record(z.string(), amount), // Indicator values on the last bar, by series key.
  lastEvaluation: z
    .object({ side: z.enum(['entry', 'exit']), conditions: z.array(ConditionResultSchema) })
    .nullable(), // The last bar's rule check; may predate a fill.
  stopLossPercent: amount,
  takeProfitPercent: amount.nullable(),
  ordersSubmitted: z.number().int(),
  ordersBlocked: z.number().int(),
});

export const SimulationSnapshotSchema = z.object({
  mode: z.string(),
  at: z.string(),
  sessionStartedAt: z.string(),
  revision: z.number().int(),
  instrumentId: z.string(),
  quoteCurrency: z.string().nullable(),
  baseline: z.object({ currency: z.string(), amount, at: z.string() }).nullable(), // What P&L is measured from (L2).
  equity: amount.nullable(), // Null only while holding coin with no price yet.
  realizedPnl: amount.nullable(),
  unrealizedPnl: amount,
  pnl: amount.nullable(),
  returnPercent: amount.nullable(),
  balances: z.array(BalanceSchema), // The instrument's two currencies.
  otherHoldings: z.array(BalanceSchema), // Everything else; outside the performance numbers (L4).
  position: PositionSchema.nullable(),
  openOrders: z.array(
    z.object({
      clientOrderId: z.string(),
      side: z.string(),
      type: z.string(),
      quantity: amount,
      status: z.string(),
      submittedAt: z.string(),
    })
  ),
  killSwitch: z.boolean(),
  mandateRevoked: z.boolean(),
  strategy: StrategyStatusSchema.nullable(),
  stale: z.boolean(), // Older than the heartbeat timeout: the node's last known state.
});

/** Kinds the page knows. The feed shows any other kind generically (L7). */
export const EVENT_KINDS = [
  'NODE_STARTED',
  'NODE_STOPPED',
  'SIGNAL',
  'ENTRY_SUBMITTED',
  'ENTRY_SKIPPED',
  'ENTRY_BLOCKED',
  'EXIT_SUBMITTED',
  'FILL',
  'ORDER_REJECTED',
  'POSITION_CLOSED',
  'KILL_ENGAGED',
  'KILL_RELEASED',
  'MANDATE_REVOKED',
] as const;

/** One event. `kind` is open and the rest is kind-specific, so it passes through. */
export const SimulationEventSchema = z.looseObject({
  id: z.string(),
  kind: z.string(),
  at: z.string(),
});

export const SimulationEventPageSchema = z.object({
  events: z.array(SimulationEventSchema), // Oldest first.
  last: z.string().nullable(), // Pass back as `after` for what came since.
});

export const SimulationEquitySchema = z.object({
  points: z.array(z.object({ time: z.string(), equity: amount })), // One per closed bar, oldest first.
  last: z.string().nullable(),
});

export const EventsQuerySchema = z.object({
  after: z.string().regex(STREAM_ID).optional(),
  limit: z.coerce.number().int().min(1).max(1_000).default(100),
});

export const EquityQuerySchema = z.object({
  after: z.string().regex(STREAM_ID).optional(),
});

export type StrategyPhase = (typeof STRATEGY_PHASES)[number];
export type EventKind = (typeof EVENT_KINDS)[number];
export type ConditionResult = z.infer<typeof ConditionResultSchema>;
export type StrategyStatus = z.infer<typeof StrategyStatusSchema>;
export type SimulationSnapshot = z.infer<typeof SimulationSnapshotSchema>;
export type SimulationEvent = z.infer<typeof SimulationEventSchema>;
export type SimulationEventPage = z.infer<typeof SimulationEventPageSchema>;
export type SimulationEquity = z.infer<typeof SimulationEquitySchema>;
export type SimulationPerformance = z.infer<typeof SimulationPerformanceSchema>;

// --- fills, kept in Postgres (plan phase 4) -----------------------------------

export const FillSchema = z.object({
  tradeId: z.string(),
  side: z.string(), // BUY or SELL.
  quantity: amount,
  price: amount,
  commission: z.object({ amount, currency: z.string() }), // Never assumed to be the quote (L5).
  filledAt: z.iso.datetime(),
});

export const FillsQuerySchema = z.object({
  page: z.coerce.number().int().min(1).default(1),
  pageSize: z.coerce.number().int().min(1).max(100).default(20),
});

export const FillPageSchema = z.object({
  data: z.array(FillSchema), // Newest first.
  pagination: z.object({
    page: z.number().int(),
    pageSize: z.number().int(),
    total: z.number().int(),
    totalPages: z.number().int(),
  }),
});

export type Fill = z.infer<typeof FillSchema>;
export type FillPage = z.infer<typeof FillPageSchema>;
