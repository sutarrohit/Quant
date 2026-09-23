import { randomUUID } from 'node:crypto';

import type { BacktestRun as RunRow, PrismaClient, Strategy, StrategyVersion } from '@quant/prisma';

import { ApiError } from '../lib/api-error.js';
import { lttb } from '../lib/downsample.js';
import { engineFetch } from '../lib/engine-client.js';
import { assertMatchesSpec } from '../lib/market.js';
import type { EngineJob, EngineSeriesPage, EngineSubmitted } from '../types/engine.js';
import type { StrategySpec } from '@quant/contracts/spec';
import {
  isTerminal,
  type CreateBacktest,
  type EquityPoint,
  type EquitySeries,
  type RunStatus,
  type TradePage,
} from '@quant/contracts/backtest';

export type RunWithVersion = RunRow & {
  version: StrategyVersion & { strategy: Strategy };
  startedAt?: string | null; // From the engine, never stored.
};

const CHART_POINTS = 1_000;
const ENGINE_PAGE = 10_000; // The engine's max page.
const CACHE_SIZE = 20;

const include = { version: { include: { strategy: true } } } as const;

/**
 * Backtest runs: our durable record of the engine's jobs (D1).
 *
 * The engine's Redis forgets a job after its TTL. A run's terminal outcome is
 * copied here the first time we see it, so the result page never depends on
 * the engine remembering.
 */
export class BacktestService {
  private readonly curves = new Map<string, EquitySeries>(); // Finished curves never change.

  constructor(private readonly prisma: PrismaClient) {}

  /** Save the row, then submit. The row exists before the engine hears of it. */
  async create(userId: string, input: CreateBacktest): Promise<RunWithVersion> {
    const version = await this.prisma.strategyVersion.findFirst({
      where: { id: input.versionId, strategy: { userId, archivedAt: null } },
      include: { strategy: true },
    });
    if (!version) throw new ApiError(404, 'VERSION_NOT_FOUND', 'No such strategy version');

    assertMatchesSpec(version.spec as StrategySpec, input);

    const run = await this.prisma.backtestRun.create({
      data: {
        userId,
        versionId: version.id,
        requestId: `run_${randomUUID()}`, // Minted once; every retry reuses it.
        status: 'SUBMITTING',
        venue: input.venue,
        instrumentId: input.instrumentId,
        barType: input.barType,
        windowStart: new Date(input.start),
        windowEnd: new Date(input.end),
        startingBalances: input.startingBalances,
        makerBps: input.fees.makerBps,
        takerBps: input.fees.takerBps,
        slippageBps: input.slippageBps,
      },
      include,
    });

    return this.submit(run);
  }

  async list(userId: string, page: number, pageSize: number, strategyId?: string) {
    const where = { userId, ...(strategyId ? { version: { strategyId } } : {}) };
    const [rows, total] = await Promise.all([
      this.prisma.backtestRun.findMany({
        where,
        include,
        orderBy: { submittedAt: 'desc' },
        skip: (page - 1) * pageSize,
        take: pageSize,
      }),
      this.prisma.backtestRun.count({ where }),
    ]);

    // Refresh the unfinished ones, so the list does not show a run as running forever.
    const data = await Promise.all(rows.map((row) => this.refresh(row).catch(() => row)));
    return { data, pagination: { page, pageSize, total, totalPages: Math.ceil(total / pageSize) } };
  }

  async get(userId: string, id: string): Promise<RunWithVersion> {
    return this.refresh(await this.own(userId, id));
  }

  /** Cancel a run the engine has not started. */
  async cancel(userId: string, id: string): Promise<RunWithVersion> {
    const run = await this.own(userId, id);
    if (!run.jobId || isTerminal(run.status as RunStatus)) {
      throw new ApiError(409, 'RUN_NOT_CANCELLABLE', `The run is ${run.status.toLowerCase()}`, {
        status: run.status,
      });
    }

    const job = await engineFetch<EngineJob>(`/v1/backtests/${run.jobId}`, {
      method: 'DELETE',
      requestId: run.requestId,
    });
    return this.record(run, job);
  }

  /** The equity curve, thinned to ~1,000 points for a chart. */
  async equity(userId: string, id: string): Promise<EquitySeries> {
    const run = await this.finished(userId, id);
    const cached = this.curves.get(run.jobId);
    if (cached) return cached;

    const first = await this.series<EquityPoint>(run, 'equity_curve', 0);
    const rest = await Promise.all(
      Array.from({ length: Math.ceil(first.total / ENGINE_PAGE) - 1 }, (_, i) =>
        this.series<EquityPoint>(run, 'equity_curve', (i + 1) * ENGINE_PAGE)
      )
    );
    const points = [first, ...rest].flatMap((page) => page.rows);
    const curve = { points: lttb(points, CHART_POINTS, (p) => Number(p.equity)), total: first.total };

    if (this.curves.size >= CACHE_SIZE) this.curves.delete(this.curves.keys().next().value!);
    this.curves.set(run.jobId, curve);
    return curve;
  }

  async trades(userId: string, id: string, offset: number, limit: number): Promise<TradePage> {
    const run = await this.finished(userId, id);
    return engineFetch<TradePage>(`/v1/backtests/${run.jobId}/artifacts/trades`, {
      requestId: run.requestId,
      query: { offset, limit },
    });
  }

  private async own(userId: string, id: string): Promise<RunWithVersion> {
    const run = await this.prisma.backtestRun.findFirst({ where: { id, userId }, include });
    if (!run) throw new ApiError(404, 'RUN_NOT_FOUND', 'No such backtest run');
    return run;
  }

  private async finished(userId: string, id: string) {
    const run = await this.own(userId, id);
    if (run.status !== 'SUCCEEDED' || !run.jobId) {
      throw new ApiError(409, 'RUN_NOT_FINISHED', 'The run has no results yet', { status: run.status });
    }
    return { ...run, jobId: run.jobId };
  }

  private series<T>(run: { jobId: string; requestId: string }, name: string, offset: number) {
    return engineFetch<EngineSeriesPage<T>>(`/v1/backtests/${run.jobId}/artifacts/${name}`, {
      requestId: run.requestId,
      query: { offset, limit: ENGINE_PAGE },
    });
  }

  /**
   * Hand the run to the engine under its stored requestId.
   *
   * Safe to repeat: the engine answers a known requestId with the existing job.
   * A refusal (4xx) deletes the row, since nothing ran. An outage leaves it
   * SUBMITTING, and the next read tries again with the same id.
   */
  private async submit(run: RunWithVersion): Promise<RunWithVersion> {
    let job: EngineSubmitted;
    try {
      job = await engineFetch<EngineSubmitted>('/v1/backtests', {
        method: 'POST',
        requestId: run.requestId,
        body: {
          requestId: run.requestId,
          strategyVersionId: run.versionId,
          spec: run.version.spec,
          venue: run.venue,
          instrumentId: run.instrumentId,
          barType: run.barType,
          start: run.windowStart.toISOString(),
          end: run.windowEnd.toISOString(),
          startingBalances: run.startingBalances,
          fees: { makerBps: run.makerBps.toString(), takerBps: run.takerBps.toString() },
          slippageBps: run.slippageBps.toString(), // Top level here; inside `fees` for live.
        },
      });
    } catch (error) {
      if (error instanceof ApiError && error.status < 500) {
        await this.prisma.backtestRun.delete({ where: { id: run.id } });
        throw error;
      }
      return run;
    }

    // A replay can answer with a finished job; refresh() then copies its outcome.
    const finished = isTerminal(job.status as RunStatus);
    const updated = await this.prisma.backtestRun.update({
      where: { id: run.id },
      data: { jobId: job.jobId, ...(finished ? {} : { status: job.status }) },
      include,
    });
    return finished ? this.refresh(updated) : updated;
  }

  /** Bring a non-terminal run up to date with the engine. */
  private async refresh(run: RunWithVersion): Promise<RunWithVersion> {
    if (isTerminal(run.status as RunStatus)) return run;
    if (!run.jobId) return this.submit(run);

    let job: EngineJob;
    try {
      job = await engineFetch<EngineJob>(`/v1/backtests/${run.jobId}`, { requestId: run.requestId });
    } catch (error) {
      // The engine forgot an unfinished job (TTL or a flushed Redis). It will never finish.
      if (error instanceof ApiError && error.code === 'JOB_NOT_FOUND') {
        return this.close(run, 'FAILED', {
          errorCode: 'JOB_LOST',
          errorMessage: 'The engine no longer holds this job; run it again',
        });
      }
      throw error;
    }
    return this.record(run, job);
  }

  /** Copy the engine's view onto the row. Terminal outcomes are persisted once. */
  private async record(run: RunWithVersion, job: EngineJob): Promise<RunWithVersion> {
    const status = job.status as RunStatus;
    if (!isTerminal(status)) {
      const updated =
        status === run.status
          ? run
          : await this.prisma.backtestRun.update({ where: { id: run.id }, data: { status }, include });
      return { ...updated, startedAt: job.startedAt };
    }

    const closed = await this.close(run, status, {
      summary: job.result?.summary ?? undefined,
      errorCode: job.error?.code ?? null,
      errorMessage: job.error?.message ?? null,
      finishedAt: job.finishedAt ? new Date(job.finishedAt) : new Date(),
    });
    return { ...closed, startedAt: job.startedAt };
  }

  private async close(
    run: RunWithVersion,
    status: RunStatus,
    data: {
      summary?: object;
      errorCode?: string | null;
      errorMessage?: string | null;
      finishedAt?: Date;
    }
  ): Promise<RunWithVersion> {
    // Guarded on "still open", so two concurrent polls cannot both write the outcome.
    await this.prisma.backtestRun.updateMany({
      where: { id: run.id, status: { notIn: ['SUCCEEDED', 'FAILED', 'CANCELLED'] } },
      data: { status, finishedAt: new Date(), ...data },
    });
    return this.prisma.backtestRun.findUniqueOrThrow({ where: { id: run.id }, include });
  }
}
