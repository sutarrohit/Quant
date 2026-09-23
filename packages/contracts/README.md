# @quant/contracts

The strategy DSL, written once. `apps/server` validates with it and `apps/web`
builds forms from it, so the two cannot disagree about what a spec is.

The engine (`packages/engine_server`) validates again from its own Pydantic
models and stays authoritative — these mirror `engine/types/dsl.py` field for
field, and the `SpecError` codes are exactly the twelve it can send.

## Why plain `zod`, not `@hono/zod-openapi`

`apps/web` must not pull in Hono. `@hono/zod-openapi` extends the shared zod
instance in place, so `.openapi()` is still available on these schemas inside
`apps/server` — which imports it — without this package depending on it.

## No barrel

Import the module that defines what you need: `@quant/contracts/spec`,
`/spec-validate`, `/strategy`.
