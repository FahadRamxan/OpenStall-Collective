// Empties the e2e data folder, so every Playwright run starts the API with a fresh database.
// playwright.config.ts runs this as part of the API server command, just before the API starts.
import { mkdirSync, rmSync } from "node:fs";
import { basename } from "node:path";

const dir = process.argv[2];
// Refuse anything but the e2e folder, so a wrong argument can never delete real data.
if (!dir || basename(dir) !== ".e2e-data") {
  console.error("usage: node reset-e2e-data.mjs <path to the .e2e-data folder>");
  process.exit(1);
}

rmSync(dir, { recursive: true, force: true });
mkdirSync(dir, { recursive: true });
