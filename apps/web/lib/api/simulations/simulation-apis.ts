import type {
  CreateSimulationInput,
  Simulation,
  SimulationList,
  StartSimulationInput,
} from '@quant/contracts/simulation';

import { request } from '@/utils/request';

// One function per route in apps/server/src/routes/simulations/.

// GET /api/v1/simulations -- each with the engine's live view.
export async function getSimulations(): Promise<SimulationList> {
  return request('/simulations', { method: 'GET' });
}

// GET /api/v1/simulations/:id
export async function getSimulation(id: string): Promise<Simulation> {
  return request(`/simulations/${id}`, { method: 'GET' });
}

// POST /api/v1/simulations -- the server mints the account and asks the engine to run it.
export async function createSimulation(input: CreateSimulationInput): Promise<Simulation> {
  return request('/simulations', { method: 'POST', body: JSON.stringify(input) });
}

// POST /api/v1/simulations/:id/start -- start, restart, change version, or clear HALTED.
export async function startSimulation(id: string, input: StartSimulationInput = {}): Promise<Simulation> {
  return request(`/simulations/${id}/start`, { method: 'POST', body: JSON.stringify(input) });
}

// DELETE /api/v1/simulations/:id -- stops signalling; does not close a position.
export async function stopSimulation(id: string): Promise<Simulation> {
  return request(`/simulations/${id}`, { method: 'DELETE' });
}

// POST /api/v1/simulations/:id/kill -- a total stop, exits included.
export async function engageKill(id: string): Promise<Simulation> {
  return request(`/simulations/${id}/kill`, { method: 'POST' });
}

// DELETE /api/v1/simulations/:id/kill
export async function releaseKill(id: string): Promise<Simulation> {
  return request(`/simulations/${id}/kill`, { method: 'DELETE' });
}
