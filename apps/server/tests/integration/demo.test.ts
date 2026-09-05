import { describe, expect, it } from 'vitest';

import { client } from '../helper/client.js';

describe('app routes', () => {
  it('builds typed user route paths through the Hono test client', () => {
    expect(client.api.v1.user['onboarding-status'].$path()).toBe('/api/v1/user/onboarding-status');
    expect(client.api.v1.user['complete-onboarding'].$path()).toBe('/api/v1/user/complete-onboarding');
  });
});
