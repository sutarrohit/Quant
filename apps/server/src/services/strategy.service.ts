import type { PrismaClient, Strategy, StrategyVersion } from '@quant/prisma';

import { ApiError } from '../lib/api-error.js';
import { specHash } from '../lib/spec-hash.js';
import type { StrategySpec } from '../types/spec.js';

type WithVersions = Strategy & { versions: StrategyVersion[] };

/**
 * Strategies and their versions.
 *
 * Versions are append-only: an edit is a new row, never an UPDATE. A stored
 * backtest number only means something if the spec behind it cannot have
 * changed since.
 *
 * Every read takes a userId and filters on it. The engine has no concept of a
 * user, so ownership is answered here or not at all.
 */
export class StrategyService {
  constructor(private readonly prisma: PrismaClient) {}

  async list(userId: string): Promise<WithVersions[]> {
    return this.prisma.strategy.findMany({
      where: { userId, archivedAt: null },
      orderBy: { updatedAt: 'desc' },
      // Only the latest, since a list does not need every version.
      include: { versions: { orderBy: { version: 'desc' }, take: 1 } },
    });
  }

  /** One strategy with its full history. 404 if it is not this user's. */
  async get(userId: string, id: string): Promise<WithVersions> {
    const strategy = await this.prisma.strategy.findFirst({
      where: { id, userId, archivedAt: null },
      include: { versions: { orderBy: { version: 'desc' } } },
    });
    if (!strategy) throw new ApiError(404, 'STRATEGY_NOT_FOUND', 'No such strategy');

    return strategy;
  }

  async create(userId: string, name: string, spec: StrategySpec): Promise<WithVersions> {
    return this.prisma.strategy.create({
      data: {
        userId,
        name,
        versions: { create: { version: 1, spec, specHash: specHash(spec) } },
      },
      include: { versions: { orderBy: { version: 'desc' } } },
    });
  }

  /**
   * Append the next version.
   *
   * A spec identical to the current head returns that version rather than
   * creating a duplicate -- saving twice without editing is a no-op, not a new
   * version, and the hash is what makes that decidable.
   */
  async addVersion(userId: string, id: string, spec: StrategySpec): Promise<StrategyVersion> {
    const strategy = await this.get(userId, id);
    const head = strategy.versions[0];
    const hash = specHash(spec);

    if (head && head.specHash === hash) return head;

    // Serialisable, because two concurrent saves both reading the same head
    // would otherwise both write version N+1 and one would lose on the unique
    // index -- with the user's edit gone.
    return this.prisma.$transaction(async (tx) => {
      const latest = await tx.strategyVersion.findFirst({
        where: { strategyId: id },
        orderBy: { version: 'desc' },
      });

      const version = await tx.strategyVersion.create({
        data: { strategyId: id, version: (latest?.version ?? 0) + 1, spec, specHash: hash },
      });
      await tx.strategy.update({ where: { id }, data: { updatedAt: new Date() } });
      return version;
    });
  }

  /** Soft delete: a version a backtest points at must stay readable. */
  async archive(userId: string, id: string): Promise<void> {
    await this.get(userId, id);
    await this.prisma.strategy.update({ where: { id }, data: { archivedAt: new Date() } });
  }
}
