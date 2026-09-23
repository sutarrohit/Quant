import type { NextConfig } from 'next';

// Server-only, so the API's address never ships in the client bundle.
const API_URL = process.env.API_URL ?? 'http://localhost:4000';

const nextConfig: NextConfig = {
  reactCompiler: true,

  // Proxy the API through this app's own origin, so privy-token is always a
  // same-origin cookie and there is no CORS preflight. This is what frees the API
  // from sharing a domain with this app -- docs/privy-auth-integration.md 2.1.
  async rewrites() {
    return [{ source: '/api/v1/:path*', destination: `${API_URL}/api/v1/:path*` }];
  },
};

export default nextConfig;
