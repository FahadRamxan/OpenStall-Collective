import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Resolves the @/* import alias from tsconfig.json.
    tsconfigPaths: true,
  },
  test: {
    environment: "jsdom",
    // Component and unit tests, plus checks of the build config next to it. Playwright runs the UI tests in e2e/.
    include: ["src/**/*.test.{ts,tsx}", "*.test.ts"],
    setupFiles: ["./vitest.setup.ts"],
    restoreMocks: true,
    unstubEnvs: true,
    unstubGlobals: true,
  },
});
