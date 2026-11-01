// @vitest-environment node
import { readFileSync } from "node:fs";
import path from "node:path";

import { ESLint } from "eslint";
import { describe, expect, it, vi } from "vitest";

import playwrightConfig, { E2E_DIST_DIR } from "./playwright.config";

// The UI tests make their own production build, pointed at the e2e API. It must never replace the normal
// build in .next, or `npm start` after `npm run e2e` would serve a site that calls the wrong API.

async function loadNextConfig() {
  vi.resetModules();
  return (await import("./next.config")).default;
}

describe("the e2e build", () => {
  it("goes to its own folder", () => {
    const web = [playwrightConfig.webServer].flat().find((server) => server?.name === "Web");

    expect(web?.command).toContain("npm run build");
    expect(web?.env?.NEXT_DIST_DIR).toBe(E2E_DIST_DIR);
    expect(E2E_DIST_DIR).not.toBe(".next");
  });

  it("is where next.config.ts builds when NEXT_DIST_DIR is set, and .next otherwise", async () => {
    vi.stubEnv("NEXT_DIST_DIR", E2E_DIST_DIR);
    expect((await loadNextConfig()).distDir).toBe(E2E_DIST_DIR);

    vi.stubEnv("NEXT_DIST_DIR", undefined);
    expect((await loadNextConfig()).distDir).toBe(".next");
  });

  it("has its types listed in tsconfig.json, so building it never rewrites that file", () => {
    const { include } = JSON.parse(readFileSync(path.join(__dirname, "tsconfig.json"), "utf8")) as {
      include: string[];
    };

    expect(include).toEqual(
      expect.arrayContaining([`${E2E_DIST_DIR}/types/**/*.ts`, `${E2E_DIST_DIR}/dev/types/**/*.ts`]),
    );
  });

  // Loading Next.js's ESLint config takes about 4 seconds on its own, more while other test files run in parallel.
  it("is not linted", { timeout: 30_000 }, async () => {
    const eslint = new ESLint({ cwd: __dirname });

    expect(await eslint.isPathIgnored(path.join(__dirname, E2E_DIST_DIR, "server", "app", "page.js"))).toBe(true);
  });
});
