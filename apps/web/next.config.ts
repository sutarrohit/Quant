import type { NextConfig } from 'next';

// Server-only: never prefixed NEXT_PUBLIC_, so the API's real address does not
// ship in the client bundle. Rewrites are resolved on the Next server.
const API_URL = process.env.API_URL ?? 'http://localhost:4000';

const nextConfig: NextConfig = {
  reactCompiler: true,

  // Proxy the API through this app's own origin.
  //
  // The browser only ever talks to the Next.js origin, so the privy-token cookie
  // is always a same-origin cookie: SameSite=Strict is satisfied unconditionally
  // and there is no CORS preflight at all. Next forwards the incoming request
  // headers (Cookie included) to the destination server-to-server.
  //
  // This is what frees the API from having to share a registrable domain with
  // this app -- see docs/privy-auth-integration.md section 2.1.
  async rewrites() {
    return [{ source: '/api/v1/:path*', destination: `${API_URL}/api/v1/:path*` }];
  },
};

export default nextConfig;
