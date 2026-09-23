import { z } from 'zod';

// A backtest run as apps/server stores and returns it. The engine owns the job;
// we own the record (D1), so these shapes are ours, not the engine's.

export const RUN_STATUSES = [
  'SUBMITTING', // Row saved, engine has not confirmed the job yet.
  'QUEUED',
  'FETCHING_DATA',
  'RUNNING',
  'SUCCEEDED',
  'FAILED',
  'CANCELLED',
] as const;

export const TERMINAL_STATUSES = ['SUCCEEDED', 'FAILED', 'CANCELLED'] as const;

export const TIMEFRAME_AGGREGATION = {
  '1m': '1-MINUTE',
  '5m': '5-MINUTE',
  '15m': '15-MINUTE',
  '1h': '1-HOUR',
  '4h': '4-HOUR',
  '1d': '1-DAY',
} as const;

const bps = z.string().regex(/^\d+(\.\d+)?$/, 'a non-negative decimal string'); // Strings, so no float drift.

export const FeesSchema = z.object({ makerBps: bps, takerBps: bps });

export const CreateBacktestSchema = z
  .object({
    versionId: z.uuid(),
    venue: z.literal('BINANCE'),
    instrumentId: z.string().regex(/^[A-Z0-9]+\.[A-Z]+$/, 'e.g. SOLUSDT.BINANCE'),
    barType: z.string().min(1).max(128),
    start: z.iso.datetime({ offset: true }),
    end: z.iso.datetime({ offset: true }),
    startingBalances: z
      .array(z.string().regex(/^\d+(\.\d+)? [A-Z]{2,10}$/, 'e.g. "10000 USDT"'))
      .min(1)
      .max(8),
    fees: FeesSchema,
    slippageBps: bps,
  })
  .refine((v) => Date.parse(v.end) > Date.parse(v.start), {
    path: ['end'],
    message: 'end must be after start',
  });

/** The engine's summary, money as decimal strings. */
export const BacktestSummarySchema = z.object({
  startingEquity: z.string(),
  endingEquity: z.string(),
  totalReturn: z.string(),
  cagr: z.string(),
  maxDrawdown: z.string(),
  sharpe: z.string(),
  sortino: z.string(),
  winRate: z.string(),
  profitFactor: z.string(),
  tradeCount: z.number().int(),
  averageTrade: z.string(),
  medianTrade: z.string(),
  averageHoldingSeconds: z.number().int(),
  totalFees: z.string(),
  totalSlippage: z.string(),
  exposurePercent: z.string(),
  unrealizedPnl: z.string(),
  openPositions: z.number().int(),
});

export const BacktestRunSchema = z.object({
  id: z.uuid(),
  status: z.enum(RUN_STATUSES),
  strategyId: z.uuid(),
  strategyName: z.string(),
  versionId: z.uuid(),
  version: z.number().int(),
  venue: z.string(),
  instrumentId: z.string(),
  barType: z.string(),
  start: z.iso.datetime(),
  end: z.iso.datetime(),
  startingBalances: z.array(z.string()),
  fees: FeesSchema,
  slippageBps: z.string(),
  summary: BacktestSummarySchema.nullable(),
  error: z.object({ code: z.string(), message: z.string() }).nullable(),
  submittedAt: z.iso.datetime(),
  startedAt: z.iso.datetime().nullable(), // Only known while the engine still holds the job.
  finishedAt: z.iso.datetime().nullable(),
});

export const BacktestListQuerySchema = z.object({
  page: z.coerce.number().int().min(1).default(1),
  pageSize: z.coerce.number().int().min(1).max(100).default(20),
  strategyId: z.uuid().optional(),
});

export const BacktestListSchema = z.object({
  data: z.array(BacktestRunSchema),
  pagination: z.object({
    page: z.number().int(),
    pageSize: z.number().int(),
    total: z.number().int(),
    totalPages: z.number().int(),
  }),
});

export const EquityPointSchema = z.object({
  time: z.iso.datetime({ offset: true }),
  equity: z.string(),
  drawdown: z.string(),
});

export const EquitySeriesSchema = z.object({
  points: z.array(EquityPointSchema),
  total: z.number().int(), // Points in the full curve, before downsampling.
});

export const TradeSchema = z.object({
  entryTime: z.string(),
  exitTime: z.string(),
  side: z.string(),
  quantity: z.string(),
  entryPrice: z.string(),
  exitPrice: z.string(),
  pnl: z.string(),
  returnPct: z.string(),
  commission: z.string(),
  fees: z.string(),
  slippage: z.string(),
  holdingSeconds: z.number().int(),
});

export const TradesQuerySchema = z.object({
  offset: z.coerce.number().int().min(0).default(0),
  limit: z.coerce.number().int().min(1).max(500).default(50),
});

export const TradePageSchema = z.object({
  rows: z.array(TradeSchema),
  total: z.number().int(),
  offset: z.number().int(),
  limit: z.number().int(),
});

export type RunStatus = (typeof RUN_STATUSES)[number];
export type Fees = z.infer<typeof FeesSchema>;
export type CreateBacktestInput = z.input<typeof CreateBacktestSchema>;
export type CreateBacktest = z.infer<typeof CreateBacktestSchema>;
export type BacktestSummary = z.infer<typeof BacktestSummarySchema>;
export type BacktestRun = z.infer<typeof BacktestRunSchema>;
export type BacktestListQuery = z.input<typeof BacktestListQuerySchema>;
export type BacktestList = z.infer<typeof BacktestListSchema>;
export type EquityPoint = z.infer<typeof EquityPointSchema>;
export type EquitySeries = z.infer<typeof EquitySeriesSchema>;
export type Trade = z.infer<typeof TradeSchema>;
export type TradesQuery = z.input<typeof TradesQuerySchema>;
export type TradePage = z.infer<typeof TradePageSchema>;

export const isTerminal = (status: RunStatus): boolean => (TERMINAL_STATUSES as readonly string[]).includes(status);
