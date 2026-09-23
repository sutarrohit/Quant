import type { StrategyVersion as VersionRow } from '@quant/prisma';
import * as HttpStatusCodes from 'stoker/http-status-codes';

import { ApiError } from '../../lib/api-error.js';
import { strategyService } from '../../lib/container.js';
import { validateSpec } from '../../lib/spec-validate.js';
import type { AppRouteHandler } from '../../types/app.js';
import { StrategySpecSchema, type StrategySpec } from '../../types/spec.js';
import type { SpecError } from '../../types/strategy.js';
import type {
  archiveStrategyRoute,
  createStrategyRoute,
  createVersionRoute,
  getStrategyRoute,
  listStrategiesRoute,
  validateSpecRoute,
} from './strategy.route.js';

const toWireVersion = (version: VersionRow) => ({
  id: version.id,
  version: version.version,
  spec: version.spec,
  specHash: version.specHash,
  createdAt: version.createdAt.toISOString(),
});

const toWireStrategy = (strategy: {
  id: string;
  name: string;
  createdAt: Date;
  updatedAt: Date;
  versions: VersionRow[];
}) => ({
  id: strategy.id,
  name: strategy.name,
  createdAt: strategy.createdAt.toISOString(),
  updatedAt: strategy.updatedAt.toISOString(),
  latestVersion: strategy.versions[0] ? toWireVersion(strategy.versions[0]) : null,
  versions: strategy.versions.map(toWireVersion),
});

/**
 * Refuse a spec the engine would refuse, with the same codes.
 *
 * The schema has already passed by the time a handler runs, so this is the
 * semantic half. `details` carries the whole list so the builder marks every
 * bad field at once.
 */
function assertRunnable(spec: StrategySpec): void {
  const errors = validateSpec(spec);
  if (errors.length > 0) {
    throw new ApiError(422, 'SPEC_INVALID', 'The strategy spec is not runnable', errors);
  }
}

export const listStrategiesHandler: AppRouteHandler<typeof listStrategiesRoute> = async (c) => {
  const strategies = await strategyService.list(c.get('user').id);
  return c.json({ strategies: strategies.map(toWireStrategy) }, HttpStatusCodes.OK);
};

export const createStrategyHandler: AppRouteHandler<typeof createStrategyRoute> = async (c) => {
  const { name, spec } = c.req.valid('json');
  assertRunnable(spec);

  const strategy = await strategyService.create(c.get('user').id, name, spec);
  return c.json(toWireStrategy(strategy), HttpStatusCodes.CREATED);
};

export const getStrategyHandler: AppRouteHandler<typeof getStrategyRoute> = async (c) => {
  const strategy = await strategyService.get(c.get('user').id, c.req.valid('param').id);
  return c.json(toWireStrategy(strategy), HttpStatusCodes.OK);
};

export const createVersionHandler: AppRouteHandler<typeof createVersionRoute> = async (c) => {
  const { spec } = c.req.valid('json');
  assertRunnable(spec);

  const version = await strategyService.addVersion(
    c.get('user').id,
    c.req.valid('param').id,
    spec
  );
  return c.json(toWireVersion(version), HttpStatusCodes.CREATED);
};

export const archiveStrategyHandler: AppRouteHandler<typeof archiveStrategyRoute> = async (c) => {
  await strategyService.archive(c.get('user').id, c.req.valid('param').id);
  return c.body(null, HttpStatusCodes.NO_CONTENT);
};

export const validateSpecHandler: AppRouteHandler<typeof validateSpecRoute> = async (c) => {
  const parsed = StrategySpecSchema.safeParse(c.req.valid('json').spec);

  // A schema failure is reshaped into the same list as a semantic one, so the
  // builder has one thing to render.
  if (!parsed.success) {
    const errors: SpecError[] = parsed.error.issues.map((issue) => ({
      path: issue.path.join('.') || 'spec',
      code: 'UNKNOWN_INDICATOR',
      message: issue.message,
    }));
    return c.json({ ok: false, errors }, HttpStatusCodes.OK);
  }

  const errors = validateSpec(parsed.data);
  return c.json({ ok: errors.length === 0, errors }, HttpStatusCodes.OK);
};
