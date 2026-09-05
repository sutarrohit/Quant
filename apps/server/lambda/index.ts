import app from "../src/app.js";
import { handle } from "hono/aws-lambda";
import type { LambdaEvent, LambdaContext } from "hono/aws-lambda";

export type AppType = typeof app;
export const handler = handle(app);
