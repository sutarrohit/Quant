# AGENTS.md — apps/web (`@quant/web`)

Guidance for any coding agent working in `apps/web`. `CLAUDE.md` imports this file. The root `AGENTS.md` (working
agreement, monorepo layout) applies too.

## Commands

```bash
pnpm --filter @quant/web dev          # http://localhost:3000; needs apps/server on :4000
pnpm --filter @quant/web lint
pnpm --filter @quant/web check-types
pnpm --filter @quant/web build
```

There is no test runner in this package. Env: copy `.env.example` to `.env` (`NEXT_PUBLIC_PRIVY_APP_ID` is required).
`API_URL` (server-only, read in `next.config.ts`) defaults to `http://localhost:4000`.

## Stack

Next.js 16 App Router with the React Compiler, React 19, Tailwind 4, shadcn (`base-nova` style on `@base-ui/react`,
Remix icons), TanStack Query, react-hook-form + zod, zustand, recharts, Privy for auth. Path alias `@/*` is the package
root.

## UI: build everything from shadcn components

This is a hard rule. Every component and page is composed from the shadcn components in `components/ui/`.

The `shadcn` skill (`.agents/skills/shadcn`, symlinked into `.claude/skills`) covers composition, styling, forms and
icons. Follow it for UI work. Where it conflicts with this file (e.g. toasts, or `npx shadcn@latest` vs the pinned
local CLI), this file wins.

- **Use the shadcn primitive, never a hand-rolled one.** Buttons, inputs, selects, dialogs, sheets, tables, cards,
  badges, tooltips, forms, toasts and the like come from `@/components/ui/*`. Don't style a raw `<button>`, `<input>`,
  `<select>` or `<table>`, and don't build your own modal, dropdown or popover.
- **Missing a component? Add it with the shadcn CLI**, from `apps/web`: `pnpm exec shadcn add <component>`. The
  CLI reads `components.json` (`base-nova` style, `@base-ui/react`). Don't write a new file in `components/ui/` by hand
  or copy one in from elsewhere.
- **Don't edit generated `components/ui/` files for a one-off look.** Customise through the component's `variant`/`size`
  props and `className` (merged with `cn()` from `@/lib/utils`). Only change a `ui/` file to add a variant the whole
  app should share.
- **Forms** use the shadcn `form` components with react-hook-form and a zod resolver. **Charts** use `ui/chart`
  (recharts underneath). **Icons** come from `@remixicon/react`. **Toasts** use `sonner` via `ui/sonner`.
- **Style with Tailwind and the theme's CSS variables** (`app/globals.css`), e.g. `bg-card` and `text-muted-foreground`.
  Don't hard-code colours, so light and dark themes keep working.
- **Reuse app-level building blocks** (`page-header.tsx`, `page-states.tsx`, `metric-card.tsx`) before making new ones.

## How it fits together

- **Routes:** `app/(public)` is the landing page and `app/(protected)` is everything behind login (dashboard,
  strategies, backtests, simulations). `app/refresh` re-mints an expired Privy token and continues.
- **Auth is layered, and none of these layers is the security boundary.** `proxy.ts` redirects on cookie presence only.
  `app/(protected)/layout.tsx` covers client-side navigation that `proxy.ts` never sees. The real check is `requireAuth`
  on the API.
- **API calls** go to relative `/api/v1/*`. `next.config.ts` rewrites them to the server so the `privy-token` cookie
  stays same-origin. `utils/request.ts` also attaches a bearer token and throws `ApiError` (`utils/api-error.ts`) with
  the server's `code`, `details` and request id. Branch on `code`, never on message text.
- **Per resource**, `lib/api/<name>/`: `*-apis.ts` has one fetch function per server route. `*-queries.ts` holds the
  query-key factory and `queryOptions`/`mutationOptions`. Add new endpoints the same way and invalidate via the key
  factory.
- **Types come from `@quant/contracts`.** Don't redeclare API or spec shapes locally. Contracts are consumed from
  `dist/`, so run `pnpm --filter @quant/contracts build` after changing them.
- **State split:** server data lives in TanStack Query, live form values in react-hook-form. `stores/` (zustand,
  persisted) holds only what outlives a form, e.g. strategy-builder drafts.
- `providers/index.tsx` wires Privy, Query, theme and the toaster. Feature components live in `components/<feature>/`.
- **Money and quantities** arrive as decimal strings. Format them (`lib/format.ts`) and don't do float arithmetic on them.
