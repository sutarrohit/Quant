import { PrivyClient } from '@privy-io/node';

import env from '../env.js';

// Privy owns the session; this client only ever *verifies* tokens it issued.
// We never create, store or refresh a session server-side.
//
// `jwtVerificationKey` is what keeps verification cheap: with it, checking a
// token is a local ES256 signature check. Without it, the SDK fetches the app's
// JWKS over the network, which would put an HTTP round-trip on every request.
export const privy = new PrivyClient({
  appId: env.PRIVY_APP_ID,
  appSecret: env.PRIVY_APP_SECRET,
  jwtVerificationKey: env.PRIVY_VERIFICATION_KEY,
});
