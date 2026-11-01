import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

/** Record a test event through the real API, as any other part of OpenStall would. */
async function recordEvent(request: APIRequestContext, summary: string) {
  const response = await request.post(`${E2E_API_URL}/api/dev/events`, { data: { summary } });
  expect(response.status()).toBe(201);
}

function feed(page: Page) {
  return page.getByRole("list", { name: "Activity, newest first" });
}

async function openLive(page: Page) {
  await page.goto("/demo");
  await expect(page.getByRole("status").filter({ hasText: /^Live$/ })).toBeVisible();
}

test("an event the API records appears on /demo within 3 seconds", async ({ page, request }) => {
  await openLive(page);
  const summary = `Order reserved, e2e ${Date.now()}`;

  await recordEvent(request, summary);

  await expect(feed(page).getByText(summary)).toBeVisible({ timeout: 3_000 });
  await expect(feed(page).getByRole("listitem").first()).toContainText(summary);
});

test("two open tabs both receive the same event", async ({ browser, request }) => {
  const context = await browser.newContext();
  const first = await context.newPage();
  const second = await context.newPage();
  await openLive(first);
  await openLive(second);
  const summary = `Seen in both tabs, e2e ${Date.now()}`;

  await recordEvent(request, summary);

  await expect(feed(first).getByText(summary)).toBeVisible({ timeout: 3_000 });
  await expect(feed(second).getByText(summary)).toBeVisible({ timeout: 3_000 });
  await context.close();
});

test("events from before the page opened are shown too, newest first", async ({ page, request }) => {
  const stamp = Date.now();
  await recordEvent(request, `Earlier event ${stamp}`);
  await recordEvent(request, `Later event ${stamp}`);

  await page.goto("/demo");

  const items = feed(page).getByRole("listitem");
  await expect(items.nth(0)).toContainText(`Later event ${stamp}`);
  await expect(items.nth(1)).toContainText(`Earlier event ${stamp}`);
});

test("the feed fits a phone and a laptop screen", async ({ page, request }) => {
  const stamp = Date.now();
  for (const summary of [
    `Order ord_7f3a reserved: $815.00 across 4 makers (${stamp})`,
    `Amina was paid $216.00 on proof: DHL 1234567890 (${stamp})`,
    `Lucía dropped out; her 10 covers move to Grace and Noor (${stamp})`,
  ]) {
    await recordEvent(request, summary);
  }

  for (const width of [375, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await openLive(page);
    await expect(feed(page).getByRole("listitem").first()).toContainText(String(stamp));
    const pageWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(pageWidth).toBeLessThanOrEqual(width);
    await page.screenshot({ path: `e2e/screenshots/demo-feed-${width}.png`, fullPage: true });
  }
});
