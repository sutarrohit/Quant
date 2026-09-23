import { BacktestService } from '../services/backtest.service.js';
import { SimulationService } from '../services/simulation.service.js';
import { StrategyService } from '../services/strategy.service.js';
import { UserService } from '../services/user.service.js';
import { WalletService } from '../services/wallet.service.js';
import { prisma } from './prisma.js';
import { privy } from './privy.js';

export const userService = new UserService(prisma);
export const backtestService = new BacktestService(prisma);
export const simulationService = new SimulationService(prisma);
export const strategyService = new StrategyService(prisma);
export const walletService = new WalletService(prisma, privy);
