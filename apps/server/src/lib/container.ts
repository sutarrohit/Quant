import { UserService } from '../services/user.service.js';
import { prisma } from './prisma.js';

export const userService = new UserService(prisma);
