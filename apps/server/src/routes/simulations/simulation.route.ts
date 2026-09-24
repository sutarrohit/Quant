import { createRoute, z } from '@hono/zod-openapi';
import * as HttpStatusCodes from 'stoker/http-status-codes';
import jsonContent from 'stoker/openapi/helpers/json-content';
import jsonContentRequired from 'stoker/openapi/helpers/json-content-required';

import { ApiErrorSchema } from '@quant/contracts/error';
import {
  CreateSimulationSchema,
  EquityQuerySchema,
  EventsQuerySchema,
  SimulationEquitySchema,
  SimulationEventPageSchema,
  SimulationListSchema,
  SimulationSchema,
  SimulationSnapshotSchema,
  StartSimulationSchema,
} from '@quant/contracts/simulation';

const IdParam = z.object({ id: z.uuid() });
const unauthorized = jsonContent(ApiErrorSchema, 'Not authenticated');
const notFound = jsonContent(ApiErrorSchema, 'No such simulation');
const one = (description: string) => jsonContent(SimulationSchema, description);

export const listSimulationsRoute = createRoute({
  method: 'get',
  path: '/',
  tags: ['Simulations'],
  responses: {
    [HttpStatusCodes.OK]: jsonContent(SimulationListSchema, "The user's simulations with the engine's live view"),
    [HttpStatusCodes.UNAUTHORIZED]: unauthorized,
  },
});

export const createSimulationRoute = createRoute({
  method: 'post',
  path: '/',
  tags: ['Simulations'],
  request: { body: jsonContentRequired(CreateSimulationSchema, 'Which version to paper-trade, where, at what cost') },
  responses: {
    [HttpStatusCodes.CREATED]: one('The simulation, asked to start'),
    [HttpStatusCodes.UNPROCESSABLE_ENTITY]: jsonContent(ApiErrorSchema, 'The spec or market is not runnable'),
    [HttpStatusCodes.NOT_FOUND]: jsonContent(ApiErrorSchema, 'No such strategy version'),
    [HttpStatusCodes.UNAUTHORIZED]: unauthorized,
  },
});

export const getSimulationRoute = createRoute({
  method: 'get',
  path: '/{id}',
  tags: ['Simulations'],
  request: { params: IdParam },
  responses: {
    [HttpStatusCodes.OK]: one('The simulation with its desired and observed state'),
    [HttpStatusCodes.NOT_FOUND]: notFound,
    [HttpStatusCodes.UNAUTHORIZED]: unauthorized,
  },
});

// Start, restart after a stop, move to another version, or clear HALTED -- all one restatement.
export const startSimulationRoute = createRoute({
  method: 'post',
  path: '/{id}/start',
  tags: ['Simulations'],
  request: { params: IdParam, body: jsonContentRequired(StartSimulationSchema, 'Optionally, the version to run') },
  responses: {
    [HttpStatusCodes.OK]: one('Asked to run; the node converges on it'),
    [HttpStatusCodes.UNPROCESSABLE_ENTITY]: jsonContent(ApiErrorSchema, 'The version cannot run here'),
    [HttpStatusCodes.NOT_FOUND]: notFound,
    [HttpStatusCodes.UNAUTHORIZED]: unauthorized,
  },
});

export const stopSimulationRoute = createRoute({
  method: 'delete',
  path: '/{id}',
  tags: ['Simulations'],
  description: 'Stops signalling. Does not close an open position.',
  request: { params: IdParam },
  responses: {
    [HttpStatusCodes.OK]: one('Asked to stop'),
    [HttpStatusCodes.NOT_FOUND]: notFound,
    [HttpStatusCodes.UNAUTHORIZED]: unauthorized,
  },
});

export const engageKillRoute = createRoute({
  method: 'post',
  path: '/{id}/kill',
  tags: ['Simulations'],
  description: 'A total stop, exits included. The position becomes yours to close.',
  request: { params: IdParam },
  responses: {
    [HttpStatusCodes.OK]: one('Kill switch engaged'),
    [HttpStatusCodes.NOT_FOUND]: notFound,
    [HttpStatusCodes.UNAUTHORIZED]: unauthorized,
  },
});

export const releaseKillRoute = createRoute({
  method: 'delete',
  path: '/{id}/kill',
  tags: ['Simulations'],
  request: { params: IdParam },
  responses: {
    [HttpStatusCodes.OK]: one('Kill switch released'),
    [HttpStatusCodes.NOT_FOUND]: notFound,
    [HttpStatusCodes.UNAUTHORIZED]: unauthorized,
  },
});

// --- what the account is doing (docs/simulation-state-plan.md) ---------------

export const simulationSnapshotRoute = createRoute({
  method: 'get',
  path: '/{id}/snapshot',
  tags: ['Simulations'],
  description: 'Balances, position, P&L and the strategy status. Marked stale past the heartbeat timeout.',
  request: { params: IdParam },
  responses: {
    [HttpStatusCodes.OK]: jsonContent(SimulationSnapshotSchema, 'The latest snapshot'),
    [HttpStatusCodes.NOT_FOUND]: jsonContent(ApiErrorSchema, 'No such simulation, or SNAPSHOT_NOT_FOUND: not published yet'),
    [HttpStatusCodes.UNAUTHORIZED]: unauthorized,
  },
});

export const simulationEventsRoute = createRoute({
  method: 'get',
  path: '/{id}/events',
  tags: ['Simulations'],
  description: 'Oldest first. Without `after`, the latest `limit`; with it, what came since.',
  request: { params: IdParam, query: EventsQuerySchema },
  responses: {
    [HttpStatusCodes.OK]: jsonContent(SimulationEventPageSchema, 'Fills, signals, blocked entries, starts and stops'),
    [HttpStatusCodes.NOT_FOUND]: notFound,
    [HttpStatusCodes.UNPROCESSABLE_ENTITY]: jsonContent(ApiErrorSchema, 'A cursor that is not a stream id'),
    [HttpStatusCodes.UNAUTHORIZED]: unauthorized,
  },
});

export const simulationEquityRoute = createRoute({
  method: 'get',
  path: '/{id}/equity',
  tags: ['Simulations'],
  request: { params: IdParam, query: EquityQuerySchema },
  responses: {
    [HttpStatusCodes.OK]: jsonContent(SimulationEquitySchema, 'One point per closed bar, oldest first'),
    [HttpStatusCodes.NOT_FOUND]: notFound,
    [HttpStatusCodes.UNPROCESSABLE_ENTITY]: jsonContent(ApiErrorSchema, 'A cursor that is not a stream id'),
    [HttpStatusCodes.UNAUTHORIZED]: unauthorized,
  },
});
