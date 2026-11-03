import path from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// The allocator on the story's quote: cheapest first, 12 from Amina, 11 from Priya, 10 from Lucía and 7 from Grace,
// $815.00. Reserved shares use up makers' capacity, and approve.spec.ts leaves story orders reserved in the same
// database, so each test first releases every reserved share; the shortfall test then reserves one on purpose.
const SCREENSHOTS = path.join(__dirname, "screenshots");

function allocation(page: Page) {
  return page.getByRole("region", { name: "Allocation", exact: true });
}

/** A row of the plan table, by the seller (or "Total") it starts with: the header's "Line total" does not count. */
function planRow(page: Page, name: string) {
  return allocation(page).getByRole("row").filter({ hasText: new RegExp(`^${name}`) });
}

async function storyQuote(request: APIRequestContext) {
  expect((await request.post(`${E2E_API_URL}/api/dev/quote`)).status()).toBe(201);
}

/** The story's order, approved at the simulated PayPal page and reserved: its 12/11/10/7 are then committed. */
async function reserveStoryOrder(request: APIRequestContext) {
  const created = await request.post(`${E2E_API_URL}/api/dev/story-orders`);
  const { order_id: orderId } = (await created.json()) as { order_id: string };
  const checkout = await request.post(`${E2E_API_URL}/api/orders/${orderId}/checkout`);
  const { paypal_order_id: token } = (await checkout.json()) as { paypal_order_id: string };
  expect((await request.post(`${E2E_API_URL}/api/dev/fake-paypal/${token}/approve`)).ok()).toBeTruthy();
  expect((await request.post(`${E2E_API_URL}/api/orders/${orderId}/reserve`)).ok()).toBeTruthy();
}

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${E2E_API_URL}/api/dev/release-reserved-shares`)).ok()).toBeTruthy();
});

test("the story's quote is split 12/11/10/7, cheapest first, for $815.00", async ({ page, request }) => {
  await storyQuote(request);
  await page.goto("/demo");

  await expect(allocation(page)).toContainText("All 40 from 4 makers, $815.00");
  await expect(allocation(page).getByText("Complete")).toBeVisible();
  for (const [seller, units, total] of [
    ["Priya", "11", "$176.00"],
    ["Amina", "12", "$216.00"],
    ["Lucía", "10", "$220.00"],
    ["Grace", "7", "$203.00"],
  ]) {
    await expect(planRow(page, seller)).toContainText(units);
    await expect(planRow(page, seller)).toContainText(total);
  }
  await expect(planRow(page, "Total")).toContainText("40");
  await expect(planRow(page, "Total")).toContainText("$815.00");
  await expect(planRow(page, "Noor")).toHaveCount(0);
  // The share bar names each maker's share for screen readers, and in its legend.
  const shares = allocation(page).getByRole("list", { name: "Each maker's share of the 40" });
  await expect(shares.getByRole("listitem")).toHaveText([
    "Priya: 11 units",
    "Amina: 12 units",
    "Lucía: 10 units",
    "Grace: 7 units",
  ]);
  await shares.getByRole("listitem").first().hover();
  await expect(allocation(page).getByText("Priya · 28% of 40")).toBeVisible();
});

test("when reserved orders use up the makers, the plan says only 14 of 40 are possible", async ({ page, request }) => {
  await reserveStoryOrder(request);
  await storyQuote(request);
  await page.goto("/demo");

  await expect(allocation(page)).toContainText("Only 14 of 40 possible");
  await expect(allocation(page)).toContainText("Only 14 of 40 units can be supplied by");
  await expect(allocation(page).getByText("Short", { exact: true }).first()).toBeVisible();
  await expect(planRow(page, "Grace")).toContainText("4");
  await expect(planRow(page, "Noor")).toContainText("10");
  await expect(planRow(page, "Total")).toContainText("$411.00");
  await expect(
    allocation(page).getByRole("list", { name: "Each maker's share of the 40" }).getByRole("listitem"),
  ).toHaveText(["Grace: 4 units", "Noor: 10 units", "Short: 26 units"]);
});

test("the allocation panel fits a phone and a laptop screen", async ({ page, request }) => {
  await storyQuote(request);

  for (const width of [1280, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/demo");
    await expect(planRow(page, "Total")).toContainText("$815.00");
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await allocation(page).screenshot({ path: path.join(SCREENSHOTS, `allocation-${width}.png`) });
  }
});
