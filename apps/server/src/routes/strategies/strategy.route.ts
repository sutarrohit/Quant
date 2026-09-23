import { createRoute, z } from '@hono/zod-openapi';
import * as HttpStatusCodes from 'stoker/http-status-codes';
import jsonContent from 'stoker/openapi/helpers/json-content';
import jsonContentRequired from 'stoker/openapi/helpers/json-content-required';

import { ApiErrorSchema } from '../../types/error.js';
import {
  CreateStrategySchema,
  CreateVersionSchema,
  SpecValidationSchema,
  StrategyDetailSchema,
  StrategyListSchema,
  StrategyVersionSchema,
  ValidateSpecSchema,
} from '../../types/strategy.js';

const IdParam = z.object({ id: z.uuid() });

export const listStrategiesRoute = createRoute({
  method: 'get',
  path: '/',
  tags: ['Strategies'],
  responses: {
    [HttpStatusCodes.OK]: jsonContent(StrategyListSchema, "The user's strategies, newest first"),
    [HttpStatusCodes.UNAUTHORIZED]: jsonContent(ApiErrorSchema, 'Not authenticated'),
  },
});

export const createStrategyRoute = createRoute({
  method: 'post',
  path: '/',
  tags: ['Strategies'],
  request: { body: jsonContentRequired(CreateStrategySchema, 'Name and the first spec') },
  responses: {
    [HttpStatusCodes.CREATED]: jsonContent(StrategyDetailSchema, 'The strategy, at version 1'),
    [HttpStatusCodes.UNPROCESSABLE_ENTITY]: jsonContent(ApiErrorSchema, 'The spec is not runnable'),
    [HttpStatusCodes.UNAUTHORIZED]: jsonContent(ApiErrorSchema, 'Not authenticated'),
  },
});

export const getStrategyRoute = createRoute({
  method: 'get',
  path: '/{id}',
  tags: ['Strategies'],
  request: { params: IdParam },
  responses: {
    [HttpStatusCodes.OK]: jsonContent(StrategyDetailSchema, 'The strategy with every version'),
    [HttpStatusCodes.NOT_FOUND]: jsonContent(ApiErrorSchema, 'No such strategy'),
    [HttpStatusCodes.UNAUTHORIZED]: jsonContent(ApiErrorSchema, 'Not authenticated'),
  },
});

// POST, not PUT: a version is appended, never replaced. An identical spec
// returns the existing head rather than creating a duplicate.
export const createVersionRoute = createRoute({
  method: 'post',
  path: '/{id}/versions',
  tags: ['Strategies'],
  request: { params: IdParam, body: jsonContentRequired(CreateVersionSchema, 'The revised spec') },
  responses: {
    [HttpStatusCodes.CREATED]: jsonContent(StrategyVersionSchema, 'The new version'),
    [HttpStatusCodes.UNPROCESSABLE_ENTITY]: jsonContent(ApiErrorSchema, 'The spec is not runnable'),
    [HttpStatusCodes.NOT_FOUND]: jsonContent(ApiErrorSchema, 'No such strategy'),
    [HttpStatusCodes.UNAUTHORIZED]: jsonContent(ApiErrorSchema, 'Not authenticated'),
  },
});

export const archiveStrategyRoute = createRoute({
  method: 'delete',
  path: '/{id}',
  tags: ['Strategies'],
  request: { params: IdParam },
  responses: {
    [HttpStatusCodes.NO_CONTENT]: { description: 'Archived' },
    [HttpStatusCodes.NOT_FOUND]: jsonContent(ApiErrorSchema, 'No such strategy'),
    [HttpStatusCodes.UNAUTHORIZED]: jsonContent(ApiErrorSchema, 'Not authenticated'),
  },
});

// Answers 200 with the problems rather than 422, because asking "is this
// valid yet" is a successful question. The builder calls it as the user types.
export const validateSpecRoute = createRoute({
  method: 'post',
  path: '/validate',
  tags: ['Strategies'],
  request: { body: jsonContentRequired(ValidateSpecSchema, 'A spec to check') },
  responses: {
    [HttpStatusCodes.OK]: jsonContent(SpecValidationSchema, 'Whether it is runnable, and why not'),
    [HttpStatusCodes.UNAUTHORIZED]: jsonContent(ApiErrorSchema, 'Not authenticated'),
  },
});
