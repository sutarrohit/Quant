import { z } from 'zod';

import { StrategySpecSchema } from './spec.js';

// Codes the engine sends, mirrored exactly. The UI branches on these and must
// render our list and the engine's identically, so nothing is invented here.
export const SPEC_ERROR_CODES = [
  'UNKNOWN_INDICATOR',
  'UNSUPPORTED_OPERATOR',
  'INDICATOR_PERIOD_TOO_LARGE',
  'EMPTY_CONDITION_GROUP',
  'MISSING_STOP_LOSS',
  'SYMBOL_NOT_IN_CATALOG',
  'EXIT_CONDITION_IN_ENTRY',
  'MISSING_THRESHOLD',
  'MISSING_PERIOD',
  'AMBIGUOUS_COMPARISON',
  'INVALID_REFERENCE',
  'DUPLICATE_CONDITION',
] as const;

export const SpecErrorSchema = z.object({
  path: z.string(), // A JSON path, so the builder can mark the exact field.
  code: z.enum(SPEC_ERROR_CODES),
  message: z.string(),
});

export const SpecValidationSchema = z.object({
  ok: z.boolean(),
  errors: z.array(SpecErrorSchema),
});

export const StrategyVersionSchema = z.object({
  id: z.uuid(),
  version: z.number().int(),
  spec: z.unknown(),
  specHash: z.string(),
  createdAt: z.iso.datetime(),
});

export const StrategySchema = z.object({
  id: z.uuid(),
  name: z.string(),
  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
  latestVersion: StrategyVersionSchema.nullable(),
});

export const StrategyDetailSchema = StrategySchema.extend({
  versions: z.array(StrategyVersionSchema),
});

export const StrategyListSchema = z.object({ strategies: z.array(StrategySchema) });

export const CreateStrategySchema = z.object({
  name: z.string().min(1).max(200),
  spec: StrategySpecSchema,
});

export const CreateVersionSchema = z.object({ spec: StrategySpecSchema });

export const ValidateSpecSchema = z.object({ spec: z.unknown() });

export type SpecErrorCode = (typeof SPEC_ERROR_CODES)[number];
export type SpecError = z.infer<typeof SpecErrorSchema>;
export type SpecValidation = z.infer<typeof SpecValidationSchema>;
export type Strategy = z.infer<typeof StrategySchema>;
export type StrategyDetail = z.infer<typeof StrategyDetailSchema>;
export type StrategyList = z.infer<typeof StrategyListSchema>;
export type StrategyVersion = z.infer<typeof StrategyVersionSchema>;
export type CreateStrategyInput = z.input<typeof CreateStrategySchema>;
export type CreateVersionInput = z.input<typeof CreateVersionSchema>;
