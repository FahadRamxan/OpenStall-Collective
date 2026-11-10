import { createRequire } from "node:module";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// The design and accessibility pass (prompt 45): axe-core checks every page against WCAG 2.1 A and AA, in light and in
// dark mode, at a laptop's width and a phone's, and finds nothing. Each page is checked once its content is in.
const AXE = createRequire(__filename).resolve("axe-core/axe.min.js");
const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

type Violation = { id: string; impact: string | null; help: string; nodes: { target: string[] }[] };

async function violations(page: Page): Promise<string[]> {
  await page.addScriptTag({ path: AXE });
  const found = await page.evaluate(async (tags) => {
    const axe = (window as unknown as { axe: { run: (context: unknown, options: unknown) => Promise<{ violations: Violation[] }> } }).axe;
    const result = await axe.run(document, { runOnly: { type: "tag", values: tags } });
    return result.violations;
  }, WCAG);
  return found.map(
    (violation: Violation) =>
      `${violation.id} (${violation.impact}): ${violation.help} at ${violation.nodes
        .slice(0, 3)
        .map((node) => node.target.join(" "))
        .join(", ")}`,
  );
}

async function freshOrder(request: APIRequestContext): Promise<string> {
  expect((await request.post(`${E2E_API_URL}/api/dev/release-reserved-shares`)).status()).toBe(200);
  const response = await request.post(`${E2E_API_URL}/api/dev/story-orders`);
  expect(response.status()).toBe(201);
  return ((await response.json()) as { order_id: string }).order_id;
}

// The orders approved here hold the makers' shares: give them back, so later spec files start from free makers.
test.afterAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  expect((await api.post(`${E2E_API_URL}/api/dev/release-reserved-shares`)).ok()).toBeTruthy();
  await api.dispose();
});

// Each page, and what shows that its content is in.
const PAGES: [string, string][] = [
  ["/", "OpenStall"],
  ["/demo", "Live activity"],
  ["/status", "PayPal products"],
  ["/dashboard", "Demand Radar"],
  ["/seller-chat", "Your demo phone"],
  ["/seller-chat?seller=s_priya", "Messages with Priya"],
  ["/stall/s_priya", "Priya"],
  ["/no-such-page", "not found"],
];

test("someone who asks for less motion gets none", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/demo");
  await expect(page.getByRole("status").filter({ hasText: /^Live$/ })).toBeVisible();

  const durations = await page.evaluate(() =>
    [...document.querySelectorAll(".animate-pulse")].map((element) => getComputedStyle(element).animationDuration),
  );

  expect(durations.length).toBeGreaterThan(0); // the live feed's pulsing dot
  for (const duration of durations) expect(parseFloat(duration)).toBeLessThan(0.001);
});

for (const scheme of ["light", "dark"] as const) {
  for (const width of [1280, 375]) {
    test(`every page meets WCAG 2.1 AA in ${scheme} mode at ${width}px`, async ({ page, request }) => {
      // Contrast is judged at rest: sections fade in as a page opens, and axe would otherwise read their text halfway.
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
      await page.setViewportSize({ width, height: 900 });
      const orderId = await freshOrder(request);
      const pages: [string, string][] = [...PAGES, [`/approve/${orderId}`, "Approve and pay with PayPal"]];
      const found: string[] = [];
      for (const [path, ready] of pages) {
        await page.goto(path);
        await expect(page.getByText(ready).or(page.getByLabel(ready)).first()).toBeVisible();
        found.push(...(await violations(page)).map((violation) => `${path}: ${violation}`));
      }

      // The simulated PayPal page, and the receipt it returns to.
      await page.getByRole("button", { name: "Approve and pay with PayPal" }).click();
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Simulated PayPal (test mode)");
      found.push(...(await violations(page)).map((violation) => `/fake-paypal: ${violation}`));
      await page.getByRole("button", { name: "Approve", exact: true }).click();
      await expect(page.getByRole("heading", { level: 1, name: "Simulated PayPal is holding $815.00" })).toBeVisible();
      found.push(...(await violations(page)).map((violation) => `/approve/…/return: ${violation}`));

      expect(found).toEqual([]);
    });
  }
}
