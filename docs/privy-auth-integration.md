# Privy auth integration (Hono backend + Next.js frontend)

**Status:** proposal — nothing below is implemented yet. better-auth has been removed;
this document is the replacement plan, written for review before any Privy code lands.

---

## 1. Where we're starting from

better-auth was scaffolded but never actually wired up. What existed and has now been deleted:

| Removed | What it was |
| --- | --- |
| `apps/server/src/lib/auth.ts` | `betterAuth({...})` instance. Its HTTP handler was **never mounted** — there were no `/sign-in` / `/sign-up` endpoints. |
| `apps/server/src/middlewares/auth.middleware.ts` | A `requireAuth` middleware that **nothing imported**. |
| `better-auth` dependency | `apps/server/package.json` |
| `BETTER_AUTH_SECRET` | `src/env.ts`, `.env.example`, `.env.test` |

The frontend never had any auth code at all.

**Consequence right now:** `/api/v1/user/*` is unauthenticated and `c.get('user')` is
`undefined` at runtime. That was already true before the removal — the routes were never
guarded. It stays true until section 4 lands.

Still present, deliberately untouched (see section 6): the `session`, `account` and
`verification` tables in `prisma/schema.prisma`.

---

## 2. The model shift

better-auth was going to be *our* session store — that's why it needed three extra tables
and a signing secret. Privy is different: **Privy owns the session entirely.** Our server
never issues, stores, or refreshes a session. It only verifies a token on each request.

```
  ┌──────────┐   login()          ┌────────────┐
  │ Next.js  │ ─────────────────► │   Privy    │   (hosted login UI: email, wallet, OAuth)
  │  (web)   │ ◄───────────────── │            │
  └────┬─────┘   access token     └────────────┘
       │         (ES256 JWT, ~1h)
       │
       │  Cookie: privy-token=<jwt>   (HttpOnly, sent automatically)
       ▼
  ┌──────────┐
  │   Hono   │  verifyAccessToken(jwt)  →  { userId: "did:privy:...", sessionId, ... }
  │ (server) │  upsert local User row keyed by privyDid
  └──────────┘  → c.set('user', user)
```

Two things follow from this:

- **We use the `privy-token` HttpOnly cookie, not an `Authorization` header.** The token is
  never readable by JavaScript, which removes the XSS token-theft surface. This is viable
  because cookies are scoped by *host*, not by port or origin — see the constraint in 2.1.
- **Our `user` table stops being an identity store.** Privy holds the credential, the
  email, the linked wallets. Our row exists only to hang domain data off (onboarding,
  tenancy, exchange accounts later). It is keyed by the Privy DID.

### 2.1 The cookie constraint — read this before choosing a deploy topology

CORS and cookie scoping are two independent gates. A request only carries the cookie if it
passes **both**, and permissive CORS cannot rescue a cookie the browser declined to send.

| Gate | Controlled by | Our setting |
| --- | --- | --- |
| Will the browser *send* the cookie? | The cookie's own `Domain` + `SameSite` — set by Privy, not by us | see below |
| Will the browser *expose* the response? | Our CORS `origin` + `credentials` | `env.FRONTEND_URL`, `credentials: true` |

What Privy actually does:

- **Development:** the Privy *client* sets the cookie on whatever domain the App ID is used
  on, including `localhost`. Cookies ignore ports, so `localhost:3000` → `localhost:4000`
  works with no extra setup.
- **Production:** Privy's *servers* set the cookie on the DNS-verified base domain **and its
  subdomains**.
- **`SameSite` defaults to `Strict`**, configurable to `Lax` in the dashboard. Neither value
  is `None`.

That last line is the hard constraint. `SameSite` is evaluated on the registrable domain
(eTLD+1), so:

- ✅ `app.example.com` (web) → `api.example.com` (API) — **same-site**, cookie is sent.
- ✅ `example.com/api/*` behind one reverse proxy — same origin, no CORS needed at all.
- ❌ `ourapp.vercel.app` (web) → `api.ourdomain.com` (API) — **cross-site**. `Strict` blocks
  it, and `Lax` also blocks it (Lax permits top-level navigation, not `fetch` subresources).
  Privy exposes no `SameSite=None`, so there is no configuration that makes this work.

**So: cookie auth commits us to serving web and API from one registrable domain in
production.** If that's the plan, cookies are the better option and nothing below is a
problem. If the frontend might land on a platform domain like `*.vercel.app` while the API
sits elsewhere, this breaks at deploy time, not at review time — and the fallback is the
Bearer header.

### 2.2 Operational cost of enabling cookies

Cookie storage is opt-in; Privy's default is `localStorage`. Turning it on requires:

1. **Two separate Privy apps** — one for development, one for production. Once cookies are
   enabled on a production App ID it works *only* on its registered domain. The App ID
   currently in `.env.example` (`cmu3mt6bp029x0cl5tnp2wku4`) becomes the dev one.
2. **DNS domain verification** in the Privy dashboard for the production base domain
   (registered without protocol or `www`). Propagation can take several hours — worth
   starting before it's on the critical path.

### 2.3 CSRF

Bearer tokens are immune to CSRF because the browser never attaches them automatically.
Cookies are attached automatically, so the trade has to be paid for:

- `SameSite=Strict` is the primary defence and blocks the classic cross-site form POST.
- Our API is JSON-only, so state-changing requests carry `Content-Type: application/json`,
  which forces a CORS preflight that a strict `origin` allowlist rejects.

Those two together are adequate here. But if `SameSite` is ever relaxed to `Lax`, this needs
revisiting with a real CSRF token on state-changing routes.

---

## 3. Packages

```bash
# backend
pnpm --filter @repo/api add @privy-io/node

# frontend
pnpm --filter apps add @privy-io/react-auth
```

| Package | Version | Notes |
| --- | --- | --- |
| `@privy-io/node` | `0.34.0` | Backend verification. Pure JS (`jose` under the hood). Its `viem` / `@solana/kit` / `x402` peers are all **optional** — we don't pull them in. |
| `@privy-io/react-auth` | `3.43.0` | React/Next.js client. Requires React 18+; we're on 19. |

> ⚠️ **Do not use `@privy-io/server-auth`.** It is deprecated (last publish 2025‑09‑17).
> Most blog posts and LLM answers still show its `privy.verifyAuthToken(token)` API. The
> current package is `@privy-io/node` with a different call shape — see below.

---

## 4. Backend (Hono)

### 4.1 Environment

Add to `apps/server/src/env.ts`:

```ts
PRIVY_APP_ID: z.string().min(1),
PRIVY_APP_SECRET: z.string().min(1),
PRIVY_VERIFICATION_KEY: z.string().min(1), // public key from the Privy dashboard
```

All three are already placeheld in `.env.example`. `.env.test` needs dummy values so env
validation keeps passing under `NODE_ENV=test`.

The **verification key** is what makes this cheap: with it, token verification is a local
signature check. Without it, every single request makes a network call to Privy. Set it.

> **Don't miss the Dockerfile.** Its build stage exports placeholder values for every var in
> the Zod schema, because `prisma generate` loads `prisma.config.ts`, which imports the strict
> validator. Adding the three `PRIVY_*` vars to `env.ts` without also adding placeholders to
> the `RUN export ...` block in `apps/server/Dockerfile` breaks the image build at
> `db:generate`. (`BETTER_AUTH_SECRET` has already been removed from both.)

### 4.2 The client — `src/lib/privy.ts` (replaces the deleted `auth.ts`)

```ts
import { PrivyClient } from '@privy-io/node';
import env from '../env.js';

export const privy = new PrivyClient({
  appId: env.PRIVY_APP_ID,
  appSecret: env.PRIVY_APP_SECRET,
  jwtVerificationKey: env.PRIVY_VERIFICATION_KEY, // offline verify — no network hop per request
});
```

### 4.3 The middleware — `src/middlewares/auth.middleware.ts`

```ts
import { createMiddleware } from 'hono/factory';
import { getCookie } from 'hono/cookie';

import { ApiError } from '../lib/api-error.js';
import { privy } from '../lib/privy.js';
import { prisma } from '../lib/prisma.js';
import type { AppBinding } from '../types/index.js';

export const requireAuth = createMiddleware<AppBinding>(async (c, next) => {
  const token = getCookie(c, 'privy-token');
  if (!token) throw new ApiError(401, 'UNAUTHORIZED', 'Authentication required');

  let claims;
  try {
    claims = await privy.utils().auth().verifyAccessToken({ access_token: token });
  } catch {
    // Expired or forged. The client refreshes the session and retries — see 5.3.
    throw new ApiError(401, 'UNAUTHORIZED', 'Invalid or expired token');
  }

  // Just-in-time provisioning: Privy is the identity source of truth, so the first
  // authenticated request a user ever makes is what creates their local row.
  const user = await prisma.user.upsert({
    where: { privyDid: claims.userId },
    create: { privyDid: claims.userId },
    update: {},
  });

  c.set('user', user);
  await next();
});
```

Claims returned by `verifyAccessToken`: `userId` (the Privy DID, e.g. `did:privy:abc123`),
`appId`, `sessionId`, `issuer` (always `privy.io`), `issuedAt`, `expiration`.

### 4.4 Actually applying it

This is the step better-auth never got to, and the reason the routes are open today:

```ts
// src/routes/user/user.index.ts
const userRouter = createRouter()
  .use('*', requireAuth)
  .openapi(getOnboardingStatusRoute, getOnboardingStatusHandler)
  .openapi(completeOnboardingRoute, completeOnboardingHandler);
```

### 4.5 CORS

`create-app.ts` is already almost right — `credentials: true` with an exact `origin` is
exactly what cookie auth needs. Two notes:

```ts
cors({
  origin: env.FRONTEND_URL,       // MUST stay an exact origin
  allowHeaders: ['Content-Type'],
  allowMethods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
  credentials: true,
})
```

- **`origin` can never become `'*'`.** The browser rejects a wildcard origin on any
  credentialed request. If we ever need multiple frontends, pass a function that echoes back
  a match from an allowlist — never a wildcard.
- `allowHeaders` is currently unset. Hono reflects the preflight's requested headers when
  it's empty, so this works by accident today. Set it explicitly. No `Authorization` entry is
  needed any more.

### 4.6 Types

`AuthUser` in `src/types/index.ts` currently requires `name: string; email: string`. A
wallet-only Privy user has neither. It becomes:

```ts
export interface AuthUser {
  id: string;
  privyDid: string;
  name: string | null;
  email: string | null;
  image: string | null;
}
```

---

## 5. Frontend (Next.js)

### 5.1 Environment

```env
NEXT_PUBLIC_PRIVY_APP_ID=cmu3mt6bp029x0cl5tnp2wku4   # dev app — cookies on any host incl. localhost
NEXT_PUBLIC_PRIVY_CLIENT_ID=
```

Both go into the Zod schema in `apps/web/env.ts` alongside `NEXT_PUBLIC_API_URL`. Both are
public identifiers — the App **Secret** never touches the frontend.

Per 2.2, production uses a **different App ID** bound to the DNS-verified domain. The backend
`PRIVY_APP_ID` must be the same app as the frontend's for a given environment, or every
token fails its `aud` check.

### 5.2 Provider

`PrivyProvider` is a client component and `app/layout.tsx` is a server component — but
`providers/index.tsx` is already `"use client"`, so it nests there with no layout change:

```tsx
// apps/web/providers/index.tsx
'use client';
import { PrivyProvider } from '@privy-io/react-auth';

export default function Providers({ children }: { children: React.ReactNode }) {
  const queryClient = getQueryClient();

  return (
    <PrivyProvider
      appId={env.NEXT_PUBLIC_PRIVY_APP_ID}
      clientId={env.NEXT_PUBLIC_PRIVY_CLIENT_ID}
      config={{
        loginMethods: ['email', 'wallet'],
        embeddedWallets: { createOnLogin: 'users-without-wallets' },
      }}
    >
      <QueryClientProvider client={queryClient}>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          {children}
        </ThemeProvider>
      </QueryClientProvider>
    </PrivyProvider>
  );
}
```

`loginMethods` and `embeddedWallets` are the open question in section 7 — the values above
are a placeholder, not a decision.

### 5.3 Sending the cookie with API calls

This is where the cookie approach pays off — there is no token plumbing at all. One line:

```ts
// apps/web/utils/request.ts
export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: 'include',        // ← the whole change
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  return handleResponse(res);
}
```

`credentials: 'include'` is required even though the cookie is same-site: the default
(`same-origin`) drops it, because `:3000` → `:4000` is a different *origin* even when it is
the same *site*.

Note the ordering fix while we're here: today `...options` comes *after* `headers`, so any
caller passing `headers` silently wipes the `Content-Type`.

**Session refresh.** The access token lives ~1h. Privy's SDK refreshes it in the background
and rewrites the cookie, so this is usually invisible. If a `privy-token` is absent but a
`privy-session` cookie is present, the session needs refreshing from the client before the
next call — treat a 401 as "call `getAccessToken()` once to force a refresh, then retry",
rather than as an immediate logout.

### 5.4 Login UI

Privy hosts the entire login flow in a modal, so there's no login page to build:

```tsx
'use client';
import { usePrivy } from '@privy-io/react-auth';

export function LoginButton() {
  const { ready, authenticated, user, login, logout } = usePrivy();

  if (!ready) return <Skeleton className="h-9 w-24" />;

  return authenticated ? (
    <Button variant="ghost" onClick={logout}>
      {user?.email?.address ?? user?.wallet?.address ?? 'Sign out'}
    </Button>
  ) : (
    <Button onClick={login}>Sign in</Button>
  );
}
```

`ready` guards against a flash of the signed-out state during rehydration — check it before
reading `authenticated`.

---

## 6. Database

Privy identifies users by DID, not email. `prisma/schema.prisma` is the authoritative
schema (D‑11); `apps/server/prisma/schema.prisma` is the stale copy that gets merged in
Phase 4 per `prisma/README.md`.

```prisma
model User {
  id                    String    @id @default(uuid())
  privyDid              String    @unique          // did:privy:...
  name                  String?                    // nullable — wallet login has no name
  email                 String?   @unique          // nullable — Postgres allows multiple NULLs
  image                 String?
  onboardingCompletedAt DateTime?
  createdAt             DateTime  @default(now())
  updatedAt             DateTime  @updatedAt

  @@map("user")
}

// Session, Account and Verification are deleted — Privy owns sessions.
// emailVerified is deleted — Privy's linked-account state is the truth.
```

**Why the tables are still in the repo:** dropping `session` / `account` / `verification`
requires a destructive migration against the tables created by
`20260906125454_phase1_trials_and_symbol_snapshots`. Doing that now, and then adding
`privyDid` in a second migration once this doc is approved, means two destructive migrations
where one will do. They land together with the Privy implementation.

---

## 7. Open decisions

1. **Where do web and API get deployed?** This is now the blocking question, not a detail.
   Cookie auth requires both on one registrable domain (`app.x.com` + `api.x.com`, or one
   host with the API behind a path). Confirm that before the DNS verification in 2.2 is
   started, because a `*.vercel.app` frontend against a separately-domained API cannot use
   the cookie at all and would force the Bearer-header variant instead.

2. **What is Privy actually for here?** If it's just a login provider, `loginMethods:
   ['email']` and no embedded wallets. If the draw is the embedded wallet — signing, and
   eventually custody of exchange credentials — then `wallet` is first-class and we probably
   need a `Wallet` model linked to `User`. This changes section 5.2 and section 6.

3. **Backfill.** There are no production users, so I've assumed none. If any `user` rows
   exist in a deployed database, `privyDid` cannot be added as `@unique` `NOT NULL` without
   a backfill strategy.

4. **Planning docs.** `.planning/research/STACK.md:44` and `.planning/PROJECT.md:76,162,165`
   still name better-auth as the chosen auth. Given how decision-log-driven this repo is,
   that probably wants an ADR (`docs/adr/0004-privy-over-better-auth.md`) rather than a
   silent edit.
