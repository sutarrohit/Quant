import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "tests/**/*.test.ts"],
    coverage: {
      provider: "v8",
      include: ["src/routes/**/*.ts"]
    }
  },
  resolve: {
    // Match tsconfig's "@/*" -> repo-root mapping (e.g. "@/src/...", "@/prisma/...").
    alias: {
      "@": path.resolve(__dirname, ".")
    }
  }
});
