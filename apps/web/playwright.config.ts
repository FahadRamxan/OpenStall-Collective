import { existsSync } from "node:fs";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

/*
 * UI tests drive the real pages against the real API in fake mode.
 * They use their own ports (API 8100, web 3100) so they never collide with dev servers on 8000 and 3000.
 */
const repoRoot = path.resolve(__dirname, "..", "..");
const apiPort = Number(process.env.E2E_API_PORT || 8100);
const webPort = Number(process.env.E2E_WEB_PORT || 3100);
const apiURL = `http://127.0.0.1:${apiPort}`;
/** The e2e API, for tests that call it directly (for example to record a test event). */
export const E2E_API_URL = apiURL;
const webURL = `http://127.0.0.1:${webPort}`;

// A throwaway SQLite database in an ignored folder, emptied each time the e2e API starts.
const dataDir = path.join(__dirname, ".e2e-data");
const databaseUrl = `sqlite:///${path.join(dataDir, "openstall-e2e.db").split(path.sep).join("/")}`;
const resetDataScript = path.join(__dirname, "e2e", "support", "reset-e2e-data.mjs");

/** Where the e2e build goes (next.config.ts reads it as NEXT_DIST_DIR). tsconfig.json lists its types. */
export const E2E_DIST_DIR = ".next-e2e";

/** E2E_PYTHON if set (scripts/check_all.py sets it), else the repo's virtualenv, else `python` on PATH. */
function python(): string {
  if (process.env.E2E_PYTHON) return process.env.E2E_PYTHON;
  const venvPython =
    process.platform === "win32"
      ? path.join(repoRoot, ".venv", "Scripts", "python.exe")
      : path.join(repoRoot, ".venv", "bin", "python");
  return existsSync(venvPython) ? venvPython : "python";
}

export default defineConfig({
  testDir: "./e2e",
  // One API and one database serve every test, so tests run one at a time.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // "never": a local failure must not start a report server that keeps `npm run e2e` waiting.
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: webURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      name: "API",
      command: `node "${resetDataScript}" "${dataDir}" && "${python()}" scripts/seed_demo.py --reset --with-amina && "${python()}" -m uvicorn openstall_api.main:app --host 127.0.0.1 --port ${apiPort} --log-level warning`,
      cwd: repoRoot,
      url: `${apiURL}/health`,
      env: {
        OPENSTALL_MODE: "fake",
        PUBLIC_BASE_URL: apiURL,
        WEB_BASE_URL: webURL,
        DATABASE_URL: databaseUrl,
      },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      name: "Web",
      // A production build served by `next start`: steadier than the dev server, and what we deploy.
      // NEXT_PUBLIC_API_BASE_URL is baked in at build time, so this build talks to the e2e API. It goes to
      // its own folder (E2E_DIST_DIR), so the normal build in .next stays as it was.
      command: `npm run build && npm run start -- --hostname 127.0.0.1 --port ${webPort}`,
      url: webURL,
      env: {
        NEXT_DIST_DIR: E2E_DIST_DIR,
        NEXT_PUBLIC_API_BASE_URL: apiURL,
        NEXT_TELEMETRY_DISABLED: "1",
      },
      reuseExistingServer: false,
      timeout: 240_000,
    },
  ],
});
