import type {
  CreateSimulationInput,
  FillPage,
  Simulation,
  SimulationEquity,
  SimulationEventPage,
  SimulationList,
  SimulationSnapshot,
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

// GET /api/v1/simulations/:id/snapshot -- 404 SNAPSHOT_NOT_FOUND until the node first publishes.
export async function getSimulationSnapshot(id: string): Promise<SimulationSnapshot> {
  return request(`/simulations/${id}/snapshot`, { method: 'GET' });
}

// GET /api/v1/simulations/:id/events -- oldest first; `after` is the last page's cursor.
export async function getSimulationEvents(id: string, after?: string, limit = 200): Promise<SimulationEventPage> {
  const query = new URLSearchParams({ limit: String(limit), ...(after ? { after } : {}) });
  return request(`/simulations/${id}/events?${query}`, { method: 'GET' });
}

// GET /api/v1/simulations/:id/equity -- one point per closed bar.
export async function getSimulationEquity(id: string, after?: string): Promise<SimulationEquity> {
  return request(`/simulations/${id}/equity${after ? `?after=${after}` : ''}`, { method: 'GET' });
}

// GET /api/v1/simulations/:id/fills -- every fill, newest first, from Postgres.
export async function getSimulationFills(id: string, page: number, pageSize: number): Promise<FillPage> {
  return request(`/simulations/${id}/fills?page=${page}&pageSize=${pageSize}`, { method: 'GET' });
}
