import * as HttpStatusCodes from 'stoker/http-status-codes';

import { simulationService } from '../../lib/container.js';
import type { SimView } from '../../services/simulation.service.js';
import type { AppRouteHandler } from '../../types/app.js';
import type { RiskLimits, Simulation } from '@quant/contracts/simulation';
import type {
  createSimulationRoute,
  engageKillRoute,
  simulationEquityRoute,
  simulationFillsRoute,
  simulationEventsRoute,
  simulationSnapshotRoute,
  getSimulationRoute,
  listSimulationsRoute,
  releaseKillRoute,
  startSimulationRoute,
  stopSimulationRoute,
} from './simulation.route.js';

const toWire = (sim: SimView): Simulation => ({
  id: sim.id,
  name: sim.name,
  accountId: sim.accountId,
  strategyId: sim.version.strategyId,
  strategyName: sim.version.strategy.name,
  versionId: sim.versionId,
  version: sim.version.version,
  venue: sim.venue,
  instrumentId: sim.instrumentId,
  barType: sim.barType,
  fees: { makerBps: sim.makerBps.toString(), takerBps: sim.takerBps.toString() },
  slippageBps: sim.slippageBps.toString(),
  risk: (sim.riskLimits as RiskLimits | null) ?? null,
  createdAt: sim.createdAt.toISOString(),
  updatedAt: sim.updatedAt.toISOString(),
  live: sim.live,
  liveError: sim.liveError,
  performance: sim.performance,
});

export const listSimulationsHandler: AppRouteHandler<typeof listSimulationsRoute> = async (c) => {
  const sims = await simulationService.list(c.get('user').id);
  return c.json({ simulations: sims.map(toWire) }, HttpStatusCodes.OK);
};

export const createSimulationHandler: AppRouteHandler<typeof createSimulationRoute> = async (c) => {
  const sim = await simulationService.create(c.get('user').id, c.req.valid('json'));
  return c.json(toWire(sim), HttpStatusCodes.CREATED);
};

export const getSimulationHandler: AppRouteHandler<typeof getSimulationRoute> = async (c) => {
  const sim = await simulationService.get(c.get('user').id, c.req.valid('param').id);
  return c.json(toWire(sim), HttpStatusCodes.OK);
};

export const startSimulationHandler: AppRouteHandler<typeof startSimulationRoute> = async (c) => {
  const { versionId } = c.req.valid('json');
  const sim = await simulationService.start(c.get('user').id, c.req.valid('param').id, versionId);
  return c.json(toWire(sim), HttpStatusCodes.OK);
};

export const stopSimulationHandler: AppRouteHandler<typeof stopSimulationRoute> = async (c) => {
  const sim = await simulationService.stop(c.get('user').id, c.req.valid('param').id);
  return c.json(toWire(sim), HttpStatusCodes.OK);
};

export const engageKillHandler: AppRouteHandler<typeof engageKillRoute> = async (c) => {
  const sim = await simulationService.kill(c.get('user').id, c.req.valid('param').id, true);
  return c.json(toWire(sim), HttpStatusCodes.OK);
};

export const releaseKillHandler: AppRouteHandler<typeof releaseKillRoute> = async (c) => {
  const sim = await simulationService.kill(c.get('user').id, c.req.valid('param').id, false);
  return c.json(toWire(sim), HttpStatusCodes.OK);
};

export const simulationSnapshotHandler: AppRouteHandler<typeof simulationSnapshotRoute> = async (c) => {
  const snapshot = await simulationService.snapshot(c.get('user').id, c.req.valid('param').id);
  return c.json(snapshot, HttpStatusCodes.OK);
};

export const simulationEventsHandler: AppRouteHandler<typeof simulationEventsRoute> = async (c) => {
  const { after, limit } = c.req.valid('query');
  const page = await simulationService.events(c.get('user').id, c.req.valid('param').id, after, limit);
  return c.json(page, HttpStatusCodes.OK);
};

export const simulationEquityHandler: AppRouteHandler<typeof simulationEquityRoute> = async (c) => {
  const { after } = c.req.valid('query');
  const equity = await simulationService.equity(c.get('user').id, c.req.valid('param').id, after);
  return c.json(equity, HttpStatusCodes.OK);
};

export const simulationFillsHandler: AppRouteHandler<typeof simulationFillsRoute> = async (c) => {
  const { page, pageSize } = c.req.valid('query');
  const fills = await simulationService.fills(c.get('user').id, c.req.valid('param').id, page, pageSize);
  return c.json(fills, HttpStatusCodes.OK);
};
