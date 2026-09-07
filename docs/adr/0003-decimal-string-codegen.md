# ADR-0003: How a string-typed JSON Schema money field becomes a strict Python Decimal

**Status:** Accepted (human decision, plan `01-04` Task 1 checkpoint, 2026-09-06)
**Requirements:** FOUND-04 (D-06 — one schema, two generated languages, neither authoritative),
FOUND-09 (D-07 — a float reaching a money field fails the build)

## Context

`schemas/strategy-spec.v1.json` declares every money-shaped field as
`{"type": "string", "pattern": "^-?[0-9]+(\\.[0-9]{1,8})?$"}` — a JSON string, per D-07 and
RESEARCH.md Pitfall 3 (declaring money as `"type": "number"` with `multipleOf` generates a
constrained decimal on the Python side but a plain TypeScript `number`, the exact JS-float
representation D-07 forbids).

The open question this ADR resolves (RESEARCH.md Assumption A3): does `datamodel-code-generator`
have a documented flag that maps a pattern-constrained `"type": "string"` field to a Python
`Decimal`, or is a hand-written conversion step required?

## Spike performed

1. **Read `datamodel-codegen --help` in full**, grepped for every flag mentioning decimal,
   strict types, custom templates, and custom base classes. Two decimal-related flags exist:
   - `--use-decimal-for-multiple-of` — documented as: "Use condecimal instead of confloat for
     float/number fields with multipleOf constraint." Keyed to `"type": "number"` +
     `multipleOf`, not to `"type": "string"` + `pattern`.
   - `--deserialize-default-values {decimal,enum}` — governs deserializing a schema's declared
     **default values**, not the runtime type of an incoming field. Not applicable here (the
     money fields have no `default`).

   No flag maps a pattern-constrained string field to `Decimal`. **This closes Assumption A3: no
   such documented flag exists**, confirmed directly against the installed tool's own `--help`
   output (`datamodel-codegen 0.76.2`), not assumed from memory.

2. **Wrote a throwaway 3-field repro schema** (plain string, money-pattern string, integer) in a
   scratch directory outside the repo, per the task's instructions.

3. **Generated Pydantic v2** via
   `uv run --project engine datamodel-codegen --input-file-type jsonschema --output-model-type pydantic_v2.BaseModel`.
   Emitted money field, quoted verbatim:

   ```python
   class Model(BaseModel):
       model_config = ConfigDict(extra='forbid')
       name: str
       amount: constr(pattern=r'^-?[0-9]+(\.[0-9]{1,8})?$')
       count: int
   ```

   `amount` is `constr(...)` — a plain **constrained string**, never `Decimal`.

4. **Generated TypeScript** via `json-schema-to-typescript` from the same schema. Emitted money
   field, quoted verbatim:

   ```typescript
   export interface Test {
     name: string;
     amount: string;
     count: number;
   }
   ```

   `amount: string` — correct per D-07; no TypeScript-side action needed.

## Decision

**Option A — a hand-written wrapper module outside the generated file.** `engine/money.py` owns
`parse_money()`, which converts the known money-field names' generated `str` values into strict
`Decimal` after the generated model validates shape. The generated file
(`engine/generated/strategy_spec.py`) stays untouched and fully regenerable; the conversion step
depends on no generator internal.

The money-field name list (`{"trade_size"}` today) is maintained by hand in
`engine/dsl/spec.py`, closing Option A's one stated weakness with a schema-walking drift test
(`test_money_field_name_list_matches_schema` in `engine/tests/dsl/test_spec_contract.py`) that
recursively walks `schemas/strategy-spec.v1.json` for every field carrying the money pattern and
asserts the hand-maintained set matches exactly — so an added money field with no corresponding
list entry fails the build rather than silently emitting an un-converted string downstream.

## Rejected alternatives

- **Option B — custom template directory.** Rejected: couples the build to
  `datamodel-code-generator`'s internal Jinja template structure, which is not a stable public
  contract — a generator upgrade could silently stop applying the validator with no visible
  error.
- **Option C — custom base class via `--base-class`.** Rejected: `--base-class` is a real,
  documented flag (confirmed in the `--help` scan above), but the coercion logic would still have
  to identify money fields by pattern-matching at runtime rather than from an explicit schema
  read, trading one hand-maintained list (Option A) for an equivalent runtime heuristic with no
  net simplification.
- **A real generator flag (`flag:<name>`).** Ruled out by the `--help` scan in step 1 above — no
  such flag exists in `datamodel-code-generator 0.76.2`.

## Consequences

- `engine/money.py` (Task 3) is the sole sanctioned route from the wire decimal-string
  representation to the internal `Decimal` contract — `parse_money()`.
- `engine/dsl/spec.py` (Task 2) imports the generated model and `engine.money`, and nothing else.
- Timebox note: the plan allowed 90 minutes for this spike with Option A as the default if the
  timebox expired. It did not — the `--help` scan and the two-schema generation were conclusive
  within minutes, so this decision rests on direct evidence, not the timebox default.
