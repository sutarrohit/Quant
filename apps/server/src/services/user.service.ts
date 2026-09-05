import type { PrismaClient } from '@/prisma/generated/client.js';

import { ApiError } from '../lib/api-error.js';

// ---------------------------------------------------------------------------
// DEMO: This service encapsulates all user-related business logic.
// It follows the service-layer pattern: controllers (handlers) call into
// services, and services interact with the database via Prisma.
//
// Key patterns demonstrated here:
//   1. Constructor-based dependency injection (PrismaClient is injected).
//   2. Throwing structured ApiErrors with status codes and error codes.
//   3. Idempotent operations (completeOnboarding can be called multiple times
//      without side effects after the first call).
//   4. Selecting only the fields needed (select: { onboardingCompletedAt })
//      to avoid leaking unnecessary data.
// ---------------------------------------------------------------------------

export class UserService {
  constructor(private readonly prisma: PrismaClient) {}

  // Returns whether the user has completed onboarding.
  async getOnboardingStatus(userId: string): Promise<{ completed: boolean }> {
    const user = await this.prisma.user.findUnique({
      where: { id: userId },
    });
    if (!user) throw new ApiError(404, 'USER_NOT_FOUND', 'User not found');

    return { completed: user.id ? true : false };
  }

  // Idempotent: the `null` guard means a repeated call can't move the timestamp,
  // so the "first completed" time is preserved.
  async completeOnboarding(userId: string): Promise<void> {
    await this.prisma.user.updateMany({
      where: { id: userId, onboardingCompletedAt: null },
      data: { onboardingCompletedAt: new Date() },
    });
  }
}
