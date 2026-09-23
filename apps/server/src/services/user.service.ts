import type { PrismaClient } from '@quant/prisma';

import { ApiError } from '../lib/api-error.js';

// Handlers call services; services reach the database through Prisma.
export class UserService {
  constructor(private readonly prisma: PrismaClient) {}

  async getOnboardingStatus(userId: string): Promise<{ completed: boolean }> {
    const user = await this.prisma.user.findUnique({
      where: { id: userId },
      select: { onboardingCompletedAt: true },
    });
    if (!user) throw new ApiError(404, 'USER_NOT_FOUND', 'User not found');

    return { completed: user.onboardingCompletedAt !== null };
  }

  // The `null` guard keeps this idempotent, preserving the first completion time.
  async completeOnboarding(userId: string): Promise<void> {
    await this.prisma.user.updateMany({
      where: { id: userId, onboardingCompletedAt: null },
      data: { onboardingCompletedAt: new Date() },
    });
  }
}
