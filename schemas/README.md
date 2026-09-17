# @quant/schemas

The single source of truth for the strategy contract (D-06, FOUND-04). Neither the generated
Pydantic model nor the generated TypeScript type is authoritative -- both are build outputs of
`strategy-spec.v1.json`, so neither language can drift from the other.

## Files

- `strategy-spec.v1.json` -- the schema. Edit this, never the generated output.
- `scripts/generate.mjs` -- runs both generators. `build` writes `schemas/generated/ts/` and
  `engine/generated/`; `check-types` (`--check`) regenerates into a scratch temp directory and
  diffs against whatever is currently on disk, catching a schema edit with no matching
  regeneration.
- `guards/` -- the TypeScript and SQL float-in-money guard stubs (D-07), inert until Phase 4.

Both `schemas/generated/` and `engine/generated/` are gitignored -- neither is ever a committed
artifact (D-06). A clean checkout regenerates them automatically: `@quant/engine` declares
`@quant/schemas` as a workspace dependency, so Turbo's `test`/`build` tasks (`dependsOn: ["^build"]`
in `turbo.json`) run `@quant/schemas`'s `build` script before `@quant/engine`'s own tasks.

## The window-ordering rule is semantic validation, not a schema constraint

`fast_period < slow_period` is **not** expressed anywhere in `strategy-spec.v1.json`. JSON Schema
draft 2020-12 has no portable keyword comparing one property's value against another's, so a
schema attempting this constraint would either fail to validate or depend on a non-portable
vocabulary extension. The schema declares both windows as positive integers and stops there.

The ordering rule is enforced by `engine.dsl.spec.load_spec` (well, `dsl.spec.load_spec` --
`engine/` has no top-level `__init__.py`; see `engine/README.md`), which raises
`SpecSemanticError` naming both fields after shape validation succeeds. Do not "fix" this by
adding a schema keyword that silently does nothing -- there is no such keyword in this draft.

**No TypeScript-side enforcement of this rule exists yet.** The generated TypeScript type has no
concept of the ordering constraint; that lands in Phase 2 (DSL-02), alongside the rest of the
DSL's actionable-rejection-message work.

## Money fields are decimal strings, never numbers

Every money-shaped field (currently just `sizing.trade_size`) is declared
`{"type": "string", "pattern": "^-?[0-9]+(\\.[0-9]{1,8})?$"}`, not `{"type": "number"}`. Declaring
money as a JSON number with a `multipleOf` constraint generates a constrained decimal on the
Python side but emits a plain TypeScript `number` -- exactly the JS-float representation D-07
forbids. See `docs/adr/0003-decimal-string-codegen.md` for the full investigation (RESEARCH.md
Pitfall 3) and the chosen Python-side conversion mechanism (`engine/money.py::parse_money`).

## `engine/dsl/` stays free of `nautilus_trader`

Nothing under `engine/dsl/` may import, or mention in a comment or docstring, the trading
engine's package name -- the purity gate (`FOUND-06`) is a bare recursive content grep over that
directory, and a mention in prose (even explaining why it's *not* imported) makes the gate report
a violation that does not exist. State any such rule here or in `engine/README.md` instead, both
of which sit outside the grepped path.
