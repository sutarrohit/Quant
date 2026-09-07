/**
 * D-07 float-in-money guard -- TypeScript half.
 *
 * STUB. This test is deliberately skipped: TypeScript does not handle any money value in
 * Phase 1 (only the Python engine does, per D-07). It becomes real in Phase 4, when the
 * control plane first reads or writes a money-shaped field crossing the wire from
 * `schemas/strategy-spec.v1.json`'s generated TypeScript type.
 *
 * The assertion this test will make once enabled: a money value crossing the wire is `string`
 * or `bigint`, and never `number` -- the exact JS-float representation D-07 forbids. Not wired
 * into any CI job or turbo task by this plan.
 */
import { describe, it } from "vitest";

describe.skip("money-guard (TypeScript, Phase 4)", () => {
  it("rejects a money value typed as number", () => {
    // Real assertion lands in Phase 4: given a value from the generated StrategySpec type,
    // `typeof value === "string" || typeof value === "bigint"` must hold, and
    // `typeof value === "number"` must never hold, for any field the schema declares with the
    // money pattern (schemas/strategy-spec.v1.json's `^-?[0-9]+(\.[0-9]{1,8})?$`).
  });
});
