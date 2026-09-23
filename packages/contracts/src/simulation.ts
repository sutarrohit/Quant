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
