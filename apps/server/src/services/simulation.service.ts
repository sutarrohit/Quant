import { randomBytes } from 'node:crypto';

import type { PrismaClient, Simulation as SimRow, Strategy, StrategyVersion } from '@quant/prisma';

import { ApiError } from '../lib/api-error.js';
import { engineFetch } from '../lib/engine-client.js';
import { assertMatchesSpec } from '../lib/market.js';
import type { EngineKill, EngineLiveState } from '../types/engine.js';
import type { StrategySpec } from '@quant/contracts/spec';
import {
  HEARTBEAT_STALE_SECONDS,
  type CreateSimulation,
  type LiveView,
  type RiskLimits,
  type SimulationEquity,
  type SimulationEventPage,
  type SimulationPerformance,
  type SimulationSnapshot,
} from '@quant/contracts/simulation';

export type SimWithVersion = SimRow & { version: StrategyVersion & { strategy: Strategy } };
export type SimView = SimWithVersion & {
  live: LiveView | null;
  liveError: { code: string; message: string } | null;
  performance: SimulationPerformance | null;
};

type EngineSnapshot = SimulationSnapshot & { accountId?: string };

const include = { version: { include: { strategy: true } } } as const;
const LIVE_STATUSES = new Set(['STARTING', 'RECONCILING', 'RUNNING']);

/**
 * Paper-trading accounts.
 *
 * The engine keys everything by accountId and trusts its caller, so the id is
 * minted here (D3) and every call is made only after ownership is checked. The
 * engine's `GET /v1/live` lists every user's accounts and is never called.
 */
export class SimulationService {
  constructor(private readonly prisma: PrismaClient) {}

  /** Save the row, then ask the engine to run it. */
  async create(userId: string, input: CreateSimulation): Promise<SimView> {
    const version = await this.ownVersion(userId, input.versionId);
    assertMatchesSpec(version.spec as StrategySpec, input);

    const sim = await this.prisma.simulation.create({
      data: {
        userId,
        versionId: version.id,
        accountId: `sim_${randomBytes(16).toString('hex')}`,
        name: input.name,
        venue: input.venue,
        instrumentId: input.instrumentId,
        barType: input.barType,
        makerBps: input.fees.makerBps,
        takerBps: input.fees.takerBps,
        slippageBps: input.slippageBps,
        riskLimits: input.risk ?? undefined,
      },
      include,
    });

    try {
      await this.put(sim);
    } catch (error) {
      // A refusal means the engine never took it. An outage keeps the row, reported via liveError; Start retries.
      if (!(error instanceof ApiError) || error.status < 500) {
        await this.prisma.simulation.delete({ where: { id: sim.id } });
        throw error;
      }
    }
    return this.view(sim);
  }

  async list(userId: string): Promise<SimView[]> {
    const rows = await this.prisma.simulation.findMany({
      where: { userId },
      include,
      orderBy: { createdAt: 'desc' },
    });
    return Promise.all(rows.map((row) => this.view(row))); // One keyed read each; never the engine's list.
  }

  async get(userId: string, id: string): Promise<SimView> {
    return this.view(await this.own(userId, id));
  }

  /** Start, restart, or move to another version. Restating bumps the revision, which also clears HALTED. */
  async start(userId: string, id: string, versionId?: string): Promise<SimView> {
    let sim = await this.own(userId, id);

    if (versionId && versionId !== sim.versionId) {
      const version = await this.ownVersion(userId, versionId);
      if (version.strategyId !== sim.version.strategyId) {
        throw new ApiError(422, 'REQUEST_INVALID', 'A simulation can only move to a version of its own strategy', [
          { path: 'versionId', message: 'belongs to a different strategy' },
        ]);
      }
      assertMatchesSpec(version.spec as StrategySpec, sim);
      sim = await this.prisma.simulation.update({ where: { id }, data: { versionId }, include });
    }

    await this.put(sim);
    return this.view(sim);
  }

  /** Stop signalling. Does not close a position. */
  async stop(userId: string, id: string): Promise<SimView> {
    const sim = await this.own(userId, id);
    await engineFetch(`/v1/live/${sim.accountId}`, { method: 'DELETE' });
    return this.view(sim);
  }

  /** A total stop, exits included. The position becomes the user's to close. */
  async kill(userId: string, id: string, engage: boolean): Promise<SimView> {
    const sim = await this.own(userId, id);
    await engineFetch<EngineKill>(`/v1/live/${sim.accountId}/kill`, { method: engage ? 'POST' : 'DELETE' });
    return this.view(sim);
  }

  /** Balances, position, P&L and what the strategy is waiting for. 404 SNAPSHOT_NOT_FOUND until the first publish. */
  async snapshot(userId: string, id: string): Promise<SimulationSnapshot> {
    const sim = await this.own(userId, id);
    const snapshot = await engineFetch<EngineSnapshot>(`/v1/live/${sim.accountId}/snapshot`);
    delete snapshot.accountId; // Stays server-side (D3).
    return snapshot;
  }

  async events(userId: string, id: string, after: string | undefined, limit: number): Promise<SimulationEventPage> {
    const sim = await this.own(userId, id);
    return engineFetch<SimulationEventPage>(`/v1/live/${sim.accountId}/events`, { query: { after, limit } });
  }

  async equity(userId: string, id: string, after: string | undefined): Promise<SimulationEquity> {
    const sim = await this.own(userId, id);
    return engineFetch<SimulationEquity>(`/v1/live/${sim.accountId}/equity`, { query: { after } });
  }

  private async own(userId: string, id: string): Promise<SimWithVersion> {
    const sim = await this.prisma.simulation.findFirst({ where: { id, userId }, include });
    if (!sim) throw new ApiError(404, 'SIMULATION_NOT_FOUND', 'No such simulation');
    return sim;
  }

  private async ownVersion(userId: string, versionId: string) {
    const version = await this.prisma.strategyVersion.findFirst({
      where: { id: versionId, strategy: { userId, archivedAt: null } },
    });
    if (!version) throw new ApiError(404, 'VERSION_NOT_FOUND', 'No such strategy version');
    return version;
  }

  /** The desired state. Always SIMULATION: this service never names a credential. */
  private put(sim: SimWithVersion) {
    return engineFetch(`/v1/live/${sim.accountId}`, {
      method: 'PUT',
      body: {
        spec: sim.version.spec,
        strategyVersionId: sim.versionId,
        venue: sim.venue,
        instrumentId: sim.instrumentId,
        barType: sim.barType,
        mode: 'SIMULATION',
        risk: (sim.riskLimits as RiskLimits | null) ?? {},
        fees: {
          makerBps: sim.makerBps.toString(),
          takerBps: sim.takerBps.toString(),
          slippageBps: sim.slippageBps.toString(), // Inside fees here; top level for a backtest.
        },
      },
    });
  }

  /** Our row plus the engine's view. An engine failure is reported on the row, not thrown. */
  private async view(sim: SimWithVersion): Promise<SimView> {
    const performance = this.performance(sim); // In parallel; never fails the row.
    try {
      const [state, kill] = await Promise.all([
        engineFetch<EngineLiveState>(`/v1/live/${sim.accountId}`),
        engineFetch<EngineKill>(`/v1/live/${sim.accountId}/kill`),
      ]);
      return { ...sim, live: toLiveView(state, kill.killSwitch), liveError: null, performance: await performance };
    } catch (error) {
      const known = error instanceof ApiError;
      return {
        ...sim,
        live: null,
        liveError: {
          code: known ? error.code : 'ENGINE_ERROR',
          message: known ? error.message : 'Could not read the engine',
        },
        performance: await performance,
      };
    }
  }

  /** The list row's glance at the snapshot. Null before the first publish or when unreadable. */
  private async performance(sim: SimWithVersion): Promise<SimulationPerformance | null> {
    try {
      const snap = await engineFetch<EngineSnapshot>(`/v1/live/${sim.accountId}/snapshot`);
      return {
        equity: snap.equity,
        pnl: snap.pnl,
        returnPercent: snap.returnPercent,
        quoteCurrency: snap.quoteCurrency,
        position: snap.position ? { side: snap.position.side, quantity: snap.position.quantity } : null,
        phase: snap.strategy?.phase ?? null,
        at: snap.at,
        stale: snap.stale,
      };
    } catch {
      return null;
    }
  }
}

function toLiveView(state: EngineLiveState, killSwitch: LiveView['killSwitch'], now = Date.now()): LiveView {
  const { desired, observed } = state;
  const live = observed !== null && LIVE_STATUSES.has(observed.status);
  const beat = observed?.heartbeatAt ? Date.parse(observed.heartbeatAt) : null;

  return {
    desired: {
      status: desired.status,
      revision: desired.revision,
      specHash: desired.specHash,
      strategyVersionId: desired.strategyVersionId,
      updatedAt: desired.updatedAt,
    },
    observed,
    leaseHolder: state.leaseHolder,
    killSwitch,
    // Either way: starting a new revision, or stopping. A stop is a revision too.
    converging: observed === null ? desired.status === 'RUNNING' : observed.revision !== desired.revision,
    heartbeatStale: live && (beat === null || now - beat > HEARTBEAT_STALE_SECONDS * 1000),
  };
}
