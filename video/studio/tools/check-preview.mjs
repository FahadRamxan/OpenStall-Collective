// Smoke test for the live preview (not the render): opens the page in headless Chromium, plays from a few points
// and reports the clock and each screen recording's <video> state. Needs `node tools/serve.mjs` running? No: it
// starts its own server. Run: node tools/check-preview.mjs
import { chromium } from "playwright-core";
import { startServer } from "./serve.mjs";

const PORT = 5600 + Math.floor(Math.random() * 300);
const server = await startServer(PORT);
const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
try {
  for (const start of [62, 88.3, 135.5]) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(`http://127.0.0.1:${PORT}/studio/?t=${start}`);
    await page.waitForFunction(() => window.__ready || window.__error, null, { timeout: 60000 });
    await page.click("#play");
    await page.waitForTimeout(2500);
    const state = await page.evaluate(() => ({
      clock: document.getElementById("time").textContent,
      videos: [...document.querySelectorAll("video")]
        .filter((v) => v.src && !v.paused)
        .map((v) => `${v.src.split("/").pop()} @${v.currentTime.toFixed(2)}s x${v.playbackRate.toFixed(2)}`),
    }));
    console.log(`from ${start}s ->`, state.clock, "|", state.videos.join(", ") || "(no clip playing)", errors.length ? "ERRORS: " + errors.join("; ") : "");
    await page.close();
  }
} finally {
  await browser.close();
  server.close();
}
