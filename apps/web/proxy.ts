import { NextResponse, type NextRequest } from 'next/server';

// Everything not listed here is public.
const PROTECTED_PREFIXES = ['/dashboard', '/strategies', '/backtests', '/simulations'];

// A UX gate, not a security boundary: this checks only that a cookie is present,
// never its signature. requireAuth on the Hono API is the real boundary.
//
// Server Functions are POSTs to their own route, so the matcher can drop coverage
// for one silently -- authorize inside each, never on the strength of this file.
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const isProtected = PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  );
  if (!isProtected) return NextResponse.next();

  if (request.cookies.has('privy-token')) return NextResponse.next(); // Definitely signed in.

  const redirectTo = (path: string) => {
    const url = request.nextUrl.clone();
    url.pathname = path;
    url.search = '';
    url.searchParams.set('redirect_uri', pathname);
    return NextResponse.redirect(url);
  };

  // Token expired but the session lives: re-login would sign out a user who is still
  // authenticated, so bounce through /refresh, which re-mints and continues.
  if (request.cookies.has('privy-session')) return redirectTo('/refresh');

  // The landing page opens the Privy modal when it sees redirect_uri.
  return redirectTo('/');
}

export const config = {
  // `api` excluded: those calls need the Hono API's JSON 401, not an HTML redirect
  // that fetch() would follow into a 200 with an unparseable body.
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
};
