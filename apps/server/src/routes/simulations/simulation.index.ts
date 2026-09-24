import { createRouter } from '../../lib/create-app.js';
import { requireAuth } from '../../middlewares/index.middleware.js';

import {
  createSimulationHandler,
  engageKillHandler,
  getSimulationHandler,
  listSimulationsHandler,
  releaseKillHandler,
  simulationEquityHandler,
  simulationFillsHandler,
  simulationEventsHandler,
  simulationSnapshotHandler,
  startSimulationHandler,
  stopSimulationHandler,
} from './simulation.handler.js';
import {
  createSimulationRoute,
  engageKillRoute,
  getSimulationRoute,
  listSimulationsRoute,
  releaseKillRoute,
  simulationEquityRoute,
  simulationFillsRoute,
  simulationEventsRoute,
  simulationSnapshotRoute,
  startSimulationRoute,
  stopSimulationRoute,
} from './simulation.route.js';

// Mounted at /api/v1/simulations.
const simulationRouter = createRouter();

simulationRouter.use('*', requireAuth);

export default simulationRouter
  .openapi(listSimulationsRoute, listSimulationsHandler)
  .openapi(createSimulationRoute, createSimulationHandler)
  .openapi(getSimulationRoute, getSimulationHandler)
  .openapi(startSimulationRoute, startSimulationHandler)
  .openapi(stopSimulationRoute, stopSimulationHandler)
  .openapi(engageKillRoute, engageKillHandler)
  .openapi(releaseKillRoute, releaseKillHandler)
  .openapi(simulationSnapshotRoute, simulationSnapshotHandler)
  .openapi(simulationEventsRoute, simulationEventsHandler)
  .openapi(simulationEquityRoute, simulationEquityHandler)
  .openapi(simulationFillsRoute, simulationFillsHandler);
