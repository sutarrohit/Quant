import { z } from '@hono/zod-openapi';

export const CatalogInstrumentSchema = z.object({
  instrumentId: z.string(), // A Nautilus instrument id, e.g. "SOLUSDT.BINANCE".
});

/** A bar type with the window the catalog holds for it. */
export const CatalogBarTypeSchema = z.object({
  barType: z.string(),
  start: z.string().nullable(), // Null means the bar type is known but nothing is ingested.
  end: z.string().nullable(),
});

export const CatalogSchema = z.object({
  instruments: z.array(CatalogInstrumentSchema),
  barTypes: z.array(CatalogBarTypeSchema),
});

export type CatalogInstrument = z.infer<typeof CatalogInstrumentSchema>;
export type CatalogBarType = z.infer<typeof CatalogBarTypeSchema>;
export type Catalog = z.infer<typeof CatalogSchema>;
