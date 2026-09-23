import { StrategyService } from '../services/strategy.service.js';
import { UserService } from '../services/user.service.js';
import { WalletService } from '../services/wallet.service.js';
import { prisma } from './prisma.js';
import { privy } from './privy.js';

export const userService = new UserService(prisma);
export const strategyService = new StrategyService(prisma);
export const walletService = new WalletService(prisma, privy);
