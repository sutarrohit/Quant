import { pinoLogger as logger } from 'hono-pino';
import pino from 'pino';
import pretty from 'pino-pretty';

// import env from "@/env";
const env = process.env;

function pinoLogger() {
  return logger({
    pino: pino(
      {
        level: env.LOG_LEVEL || 'info',
      },
      env.NODE_ENV === 'production' ? undefined : pretty()
    ),

    http: { referRequestIdKey: 'requestId' }, // Hono's requestId middleware sets it first.
  });
}

export default pinoLogger;
