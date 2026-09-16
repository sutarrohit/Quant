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

- **We use the `privy-token` cookie, not an `Authorization` header.** In production it is
  HttpOnly and therefore unreadable by page scripts, which removes the XSS token-theft
  surface. **In development it is not** — see 2.2. This is viable at all because cookies are
  scoped by *host*, not by port or origin — see 2.1.
- **Our `user` table stops being an identity store.** Privy holds the credential, the
  email, the linked wallets. Our row exists only to hang domain data off (onboarding,
  tenancy, exchange accounts later). It is keyed by the Privy DID.

### 2.1 Cookie scoping vs CORS — two independent gates

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

`SameSite` is evaluated on the registrable domain (eTLD+1), so **if the browser called the
API directly**, this would be a hard constraint:

- ✅ `app.example.com` (web) → `api.example.com` (API) — same-site, cookie is sent.
- ❌ `ourapp.vercel.app` (web) → `api.ourdomain.com` (API) — cross-site. `Strict` blocks it,
  and `Lax` also blocks it (Lax permits top-level navigation, not `fetch` subresources).
  Privy exposes no `SameSite=None`, so no configuration makes this work.

### 2.1.1 The API rewrite dissolves it

**The browser does not call the API directly.** `next.config.ts` rewrites `/api/v1/:path*` to
the API server-side, so every request the browser makes is to the Next.js app's own origin:

```
browser ──same-origin──► Next.js ──server-to-server──► Hono API
        (cookie always                (Next forwards the
         sent; no CORS)                Cookie header)
```

Three consequences, and they are the reason this is worth doing:

1. **The cookie is always same-origin.** `SameSite=Strict` is satisfied unconditionally.
   There is no cross-site case left to reason about.
2. **CORS stops applying.** No preflight, no `credentials` negotiation, no origin allowlist
   for normal traffic. The API's CORS config becomes defence-in-depth for direct access
   rather than load-bearing.
3. **The API no longer needs to share a domain with the web app.** It can sit on any host.

What remains is a much weaker requirement: **the web app must be on a domain you can
DNS-verify with Privy**, because that is where Privy sets the cookie. A `*.vercel.app`
frontend still cannot use cookie auth — you cannot verify a domain you do not own — but that
is a constraint on one domain, not on the relationship between two.

**Cost:** every API call takes an extra hop through the Next.js server, which on a serverless
host is also an extra function invocation. Fine for request/response JSON. When a live market
feed arrives later, that should bypass the rewrite rather than be tunnelled through it.

### 2.2 Operational cost of enabling cookies

Thanks to the Bearer fallback in 4.3, none of this blocks local development — it is required
only for the production HttpOnly path.

Cookie storage is opt-in; Privy's default is `localStorage`. Turning it on requires **two
separate Privy apps**, because a cookie-enabled production App ID "will only work in your
production environment, and will error in all other environments." The App ID currently in
`.env.example` (`cmu3mt6bp029x0cl5tnp2wku4`) becomes the dev one.

The two behave differently in a way worth understanding before testing locally:

| | Development app ID | Production app ID |
| --- | --- | --- |
| Who sets the cookie | Privy's **client**, via JavaScript | Privy's **servers**, via `Set-Cookie` |
| Where it lands | **any** domain, `localhost` included | only the DNS-verified domain + subdomains |
| DNS verification | not required | required |
| Cookie lifetime | 7 days | 30 days |

Two consequences:

- **No domain is needed to start.** Enable cookies on a dev app ID and `localhost:3000` works
  immediately. DNS verification (registered without protocol or `www`, propagation measured in
  hours) is a production-only task — but worth starting before it is on the critical path.
- **`HttpOnly` only holds in production.** A cookie set by JavaScript cannot carry the
  `HttpOnly` flag — `document.cookie` cannot set it; only a server can, via `Set-Cookie`.
  Privy does not state this outright, but it follows from the platform rule and matches their
  describing the shorter dev lifetime as "a security precaution". So the local cookie is
  readable by page scripts. Everything else — cookie name, request flow, `requireAuth` — is
  identical, so local testing still validates correctness; it just does not validate the
  XSS property. Do not read "it works locally" as having proven that.

### 2.3 CSRF

Bearer tokens are immune to CSRF because the browser never attaches them automatically.
Cookies are attached automatically, so the trade has to be paid for:

- `SameSite=Strict` is the primary defence and blocks the classic cross-site form POST.
- Our API is JSON-only, so state-changing requests carry `Content-Type: application/json`,
  which forces a CORS preflight that a strict `origin` allowlist rejects.

**The API rewrite changes the weight these carry.** Proxied calls are same-origin, so they are not
preflighted — the second defence does not apply to them, and protection rests on
`SameSite=Strict` alone. That is still sound: `Strict` withholds the cookie from any request
initiated by another site, including a cross-origin `fetch` with `credentials: 'include'`
aimed at our own rewrite path.

But it means the margin is thinner than it looks. If `SameSite` is ever relaxed to `Lax` in
the dashboard, this needs a real CSRF token on state-changing routes — there is no longer a
preflight quietly backing it up.

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
  const cookieToken = getCookie(c, 'privy-token');
  // Capture, don't strip: a bare `Authorization: Bearer` must not yield the
  // literal string "Bearer" as the token.
  const headerToken = c.req.header('authorization')?.match(/^Bearer\s+(\S.*)$/i)?.[1]?.trim();
  const token = cookieToken || headerToken;
  if (!token) throw new ApiError(401, 'UNAUTHORIZED', 'Authentication required');

  let claims;
  try {
    claims = await privy.utils().auth().verifyAccessToken(token);
  } catch {
    // Expired or forged. The client refreshes the session and retries — see 5.3.
    throw new ApiError(401, 'UNAUTHORIZED', 'Invalid or expired token');
  }

  // Just-in-time provisioning: Privy is the identity source of truth, so the first
  // authenticated request a user ever makes is what creates their local row.
  const user = await prisma.user.upsert({
    where: { privyDid: claims.user_id },
    create: { privyDid: claims.user_id },
    update: {},
  });

  c.set('user', user);
  await next();
});
```

**Both a cookie and a Bearer header are accepted**, cookie first. The cookie is the
production path; the header is what makes local development work before cookies are enabled
in the Privy dashboard, since a fresh Privy app defaults to `localStorage` and sets no cookie
at all. Accepting both adds no CSRF surface — a cross-origin attacker cannot set a custom
header without our CORS approval — so this costs nothing and takes dashboard setup off the
critical path.

**The token carries no profile data.** Its claims are the DID and session metadata — no
email, no name. So `requireAuth` provisions with a read-then-create rather than an upsert,
and fetches the profile from Privy's API on first sight of a user:

```ts
let user = await prisma.user.findUnique({ where: { privyDid: claims.user_id } });
if (!user) {
  const privyUser = await privy.users()._get(claims.user_id);   // by DID
  const profile = profileFromLinkedAccounts(privyUser.linked_accounts);
  user = await prisma.user.create({ data: { privyDid: claims.user_id, ...profile } });
}
```

Three things about that shape are deliberate:

- **Read-then-create, not upsert.** The profile fetch must happen once per user lifetime, not
  per request. Keying it off "row has no email" would re-fetch forever for wallet-only users,
  who legitimately never have one.
- **`_get`, with the underscore.** `PrivyUsersService` shadows the inherited `get()` with an
  identity-token parser, so the by-DID lookup is exposed as `_get`. An identity token would
  avoid the API call, but needs dashboard configuration and is explicitly documented as
  possibly incomplete "due to the size constraints of the identity token".
- **A failed lookup is non-fatal.** The token already verified, so the request *is*
  authenticated; failing it because Privy's REST API blipped is worse than a row with null
  profile fields. The create is also wrapped, because two concurrent first requests both see
  no row and one loses the unique index.

Profile fields come from *linked accounts*, whose shapes differ by login method — and this is
the part that surprises: **an email-OTP login carries no name.** `LinkedAccountEmail` is just
`{ type: 'email', address }`. Only OAuth providers carry `name`. So signing in with an
`@gmail.com` address via email OTP yields an email and a null name; signing in via *Google*
(`google_oauth`) yields both. Null name is correct behaviour, not a missing field.

Claims returned by `verifyAccessToken` are **snake_case**: `user_id` (the Privy DID, e.g.
`did:privy:abc123`), `app_id`, `session_id`, `issuer` (always `privy.io`), `issued_at`,
`expiration`.

> ⚠️ **Privy's own docs are wrong here, in two ways.** They show
> `verifyAccessToken({ access_token: token })` returning `claims.userId`. Against
> `@privy-io/node@0.34.0`'s published types, the `privy.utils().auth()` method takes a **bare
> string**, and the response type `VerifyAccessTokenResponse` is snake_case. Writing
> `claims.userId` compiles to `undefined` and would silently provision every user with a null
> DID. (The *standalone* `verifyAccessToken({ access_token, app_id, verification_key })` export
> does take an object — that is the shape the docs are describing, but it is a different
> function from the client method.) Verified by reading the package's `.d.ts`, not the docs.

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
  allowHeaders: ['Content-Type', 'Authorization'],
  allowMethods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
  credentials: true,
})
```

- **CORS is now defence-in-depth, not load-bearing.** Normal traffic arrives via the rewrite as
  a server-to-server call, which CORS does not apply to at all. This config only governs a
  browser reaching the API *directly* — keep it strict precisely because that is the path we
  do not intend anyone to use.
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
    <PrivyProvider appId={env.NEXT_PUBLIC_PRIVY_APP_ID} clientId={env.NEXT_PUBLIC_PRIVY_CLIENT_ID}>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          {children}
        </ThemeProvider>
      </QueryClientProvider>
    </PrivyProvider>
  );
}
```

**No `config` is passed, deliberately.** Two reasons, both verified against
`@privy-io/react-auth@3.43.0`'s types:

- `config.loginMethods` can only display a **subset of the methods already enabled in the
  Privy dashboard** — it cannot add one. Omitting it keeps the dashboard as the single place
  that decision lives, rather than splitting it across two.
- `config.embeddedWallets` defaults to `'off'`, and enabling it is the product decision in
  section 7.2. Its real shape is **per-chain**, not the flat form Privy's docs show:
  `embeddedWallets: { ethereum: { createOnLogin: 'users-without-wallets' } }`.

`clientId` is optional in the SDK, so `NEXT_PUBLIC_PRIVY_CLIENT_ID` is optional in
`apps/web/env.ts` too — only some dashboard configurations issue one.

### 5.3 Sending credentials with API calls

`credentials: 'include'` carries the cookie; `getAccessToken()` supplies a Bearer header as a
fallback for when Privy is still on its default `localStorage` storage and no cookie exists.
Sending both means local development needs no dashboard setup, and production still uses the
HttpOnly cookie path:

```ts
// apps/web/utils/request.ts
const API_BASE = '/api/v1';   // relative — the rewrite in next.config.ts forwards it

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    },
  });

  return handleResponse(res);
}
```

`getAccessToken()` is wrapped in a try/catch at the call site — it throws rather than
returning `null` when reached during SSR or before Privy has rehydrated.

The base is **relative**, which is what routes the call through the rewrite. A side benefit:
`NEXT_PUBLIC_API_URL` is gone entirely — the API's address is now `API_URL` in
`next.config.ts`, server-only, and no longer ships in the client bundle.

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

### 5.5 Public and protected routes

Route groups split the tree without affecting URLs:

```
app/
  layout.tsx              root — Providers (PrivyProvider lives here)
  (public)/
    page.tsx              /
    login/page.tsx        /login
  (protected)/
    layout.tsx            client-side guard + app chrome
    dashboard/page.tsx    /dashboard
  refresh/page.tsx        /refresh — session-refresh bounce
proxy.ts                  request gate (project root, beside app/)
```

> **Two different things are called "proxy" here.** Next 16 renamed the
> `middleware.ts` convention to **`proxy.ts`** (the function must be named `proxy`; one
> still named `middleware` is never called). That is unrelated to the **API rewrite** in
> `next.config.ts` from section 2.1.1. Below, "Proxy" capitalised means `proxy.ts`;
> "the rewrite" means the `next.config.ts` forwarding.

Gating happens in three places, and it matters that only one of them is a security boundary:

| Layer | Checks | Is it a security boundary? |
| --- | --- | --- |
| `proxy.ts` (Next's Proxy) | whether the `privy-token` cookie *exists* | **No** |
| `(protected)/layout.tsx` | `usePrivy().authenticated` on the client | **No** |
| `requireAuth` on the API | the token's ES256 signature | **Yes** |

The first two only stop protected *chrome* from rendering to someone obviously signed out.
Neither verifies anything — a cookie's presence is not proof it is valid. **Never render data
that did not come back through the API**, which is the only layer that actually verifies.

Proxy exists because a full page load would otherwise flash protected UI; the layout guard
exists because a *client-side* navigation into the group does not re-run Proxy.

Next's own documentation is blunt about this: Proxy "should not be used as a full session
management or authorization solution". It is an optimistic check, and we treat it as one.

**Server Functions are the trap.** They are not separate routes — they are POSTs to whichever
route uses them, so a matcher that excludes a path excludes its Server Functions too, and
moving one to a different route can silently drop Proxy coverage. Any Server Function added
later must authorize itself rather than inherit protection from `proxy.ts`.

**The `privy-session` case.** If `privy-token` is absent but `privy-session` is present, the
access token expired while the session is still alive. Redirecting to `/login` there would
sign out a user who is actually authenticated. Instead Proxy redirects to `/refresh`,
which calls `getAccessToken()` — re-minting the token and rewriting the cookie — and then
continues to the original destination, carried through as `?redirect_uri=`.

**The matcher excludes `/api`.** Rewritten API calls must receive the Hono API's JSON 401. If
Proxy redirected them, `fetch` would follow the redirect and get HTML with a 200 status,
and `handleResponse` would throw on unparseable JSON instead of surfacing an auth error.

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

**The migration is not committed.** Both `schema.prisma` files carry the change above, but
no migration SQL is in `prisma/migrations/`. That is deliberate: a hand-written migration
that does not byte-match what Prisma generates causes drift-detection pain on the next
`migrate dev`, and this change could not be generated here (no reachable database —
`.env` still holds the `.env.example` placeholders). Generate it against a real database:

```bash
pnpm --filter @repo/prisma exec prisma migrate dev --name privy_auth
```

It will `DROP TABLE` session, account and verification, drop `user.emailVerified`, make
`name`/`email` nullable, and add `user.privyDid` with a unique index. **`privyDid` is
`NOT NULL` with no default**, so this fails if the `user` table has rows — which is fine
pre-launch, and is the backfill question in section 7.3 otherwise.

Note that `apps/server` generates its Prisma client from its *own* copy of the schema
(`lib/prisma.ts` imports `../../prisma/generated/client.js`), so after migrating from the
root package, `apps/server` still needs its own `db:generate`. That duplication is the
Phase 4 merge described in `prisma/README.md`, not something this change introduces.

---

## 7. Open decisions

1. **What domain does the web app get?** Downgraded from blocking by the API rewrite in 2.1.1 —
   the API can now live anywhere. What still matters is that the *web app* runs on a domain
   you can DNS-verify with Privy, since that is where the cookie is set. A `*.vercel.app`
   URL cannot be verified; a custom domain pointed at Vercel can.

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
