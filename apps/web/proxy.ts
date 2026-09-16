import { NextResponse, type NextRequest } from 'next/server';

// Prefixes that require a session. Everything not listed here is public.
const PROTECTED_PREFIXES = ['/dashboard'];

// IMPORTANT: this is a UX gate, not a security boundary.
//
// It only checks whether a cookie is *present* -- it does not verify the token's
// signature. Its job is to avoid rendering protected UI to someone who is
// obviously signed out. The real boundary is requireAuth on the Hono API, which
// verifies the token cryptographically on every request. Next's own docs are
// explicit that Proxy "should not be used as a full session management or
// authorization solution". Never let a page render data that was not fetched
// through that API.
//
// This applies doubly to Server Functions: they are POSTs to the route that uses
// them, so a matcher that excludes a path silently excludes its Server Functions
// too, and moving one to another route can drop Proxy coverage without warning.
// Authorize inside each Server Function, never on the strength of this file.
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const isProtected = PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  );
  if (!isProtected) return NextResponse.next();

  // Definitely signed in.
  if (request.cookies.has('privy-token')) return NextResponse.next();

  const redirectTo = (path: string) => {
    const url = request.nextUrl.clone();
    url.pathname = path;
    url.search = '';
    url.searchParams.set('redirect_uri', pathname);
    return NextResponse.redirect(url);
  };

  // Access token expired but the session is still alive. Redirecting to /login
  // here would sign out a user who is actually still authenticated, so bounce
  // through /refresh, which re-mints the token client-side and continues.
  if (request.cookies.has('privy-session')) return redirectTo('/refresh');

  return redirectTo('/login');
}

export const config = {
  // `api` is excluded deliberately: API calls forwarded by the rewrite in
  // next.config.ts must receive the Hono API's JSON 401, not an HTML redirect
  // that fetch() would follow into a 200 with an unparseable body.
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
};
