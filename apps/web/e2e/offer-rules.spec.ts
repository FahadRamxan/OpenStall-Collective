import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// /demo's "Offer rules" panel shows the seed table's numbers (spec section 2). A maker's reserved shares use up her
// capacity, and approve.spec.ts runs first and leaves story orders reserved in the same database, so each test
// first releases every reserved share through the fake-mode dev helper: then every maker has her seed capacity.
const SCREENSHOTS = path.join(__dirname, "screenshots");
const DAY = new Intl.DateTimeFormat("en-US", { month: "long", day: "numeric", year: "numeric", timeZone: "UTC" });

// Spec section 2, for an order due in 30 days: the lowest price each maker's agent may offer (her floor, or her list
// price less the 15% maximum discount, whichever is higher), and what she can make and ship by then.
const SEED_TABLE = [
  { name: "Amina", lowest: "$15.30", units: 12 },
  { name: "Priya", lowest: "$13.60", units: 11 },
  { name: "Lucía", lowest: "$19.00", units: 10 },
  { name: "Grace", lowest: "$27.20", units: 11 },
  { name: "Noor", lowest: "$28.50", units: 10 },
];

/** YYYY-MM-DD, 30 days after today in UTC, the day the API counts to. */
function deadline(): string {
  const day = new Date();
  day.setUTCDate(day.getUTCDate() + 30);
  return day.toISOString().slice(0, 10);
}

function panel(page: Page) {
  return page.getByRole("region", { name: "Offer rules" });
}

/** Opens /demo once the limits have loaded. */
async function openDemo(page: Page) {
  const loaded = page.waitForResponse(
    (response) => response.request().method() === "GET" && new URL(response.url()).pathname === "/api/demo/limits",
  );
  await page.goto("/demo");
  expect((await loaded).status()).toBe(200);
}

test.beforeEach(async ({ request }) => {
  const response = await request.post(`${E2E_API_URL}/api/dev/release-reserved-shares`);
  expect(response.ok()).toBeTruthy();
});

test("the offer rules panel shows each maker's lowest price and what she can make in 30 days", async ({ page }) => {
  await openDemo(page);

  const table = panel(page).getByRole("table");
  await expect(table).toHaveAccessibleName(
    `Each maker's limits for an order due ${DAY.format(new Date(`${deadline()}T00:00:00Z`))}, 30 days from today.`,
  );
  for (const { name, lowest, units } of SEED_TABLE) {
    const row = table.getByRole("row", { name: new RegExp(`^${name}`) });
    await expect(row.getByRole("cell").nth(0)).toContainText(lowest);
    await expect(row.getByRole("cell").nth(1)).toContainText(`${units} units`);
    await expect(row.getByRole("rowheader")).toContainText("Seeded demo");
  }
  await expect(panel(page).getByRole("alert")).toHaveCount(0);
});

test("a reserved order uses up its makers' capacity, and the panel updates live", async ({ page, request }) => {
  await openDemo(page);
  const table = panel(page).getByRole("table");
  await expect(table.getByRole("row", { name: /^Amina/ }).getByRole("cell").nth(1)).toContainText("12 units");

  // The story's order, approved at the simulated PayPal page and reserved: 12/11/10/7.
  const created = await request.post(`${E2E_API_URL}/api/dev/story-orders`);
  const { order_id: orderId } = (await created.json()) as { order_id: string };
  const checkout = await request.post(`${E2E_API_URL}/api/orders/${orderId}/checkout`);
  const { paypal_order_id: token } = (await checkout.json()) as { paypal_order_id: string };
  expect((await request.post(`${E2E_API_URL}/api/dev/fake-paypal/${token}/approve`)).ok()).toBeTruthy();
  expect((await request.post(`${E2E_API_URL}/api/orders/${orderId}/reserve`)).ok()).toBeTruthy();

  const amina = table.getByRole("row", { name: /^Amina/ }).getByRole("cell").nth(1);
  await expect(amina).toContainText("0 units");
  await expect(amina).toContainText("12 already promised");
  const grace = table.getByRole("row", { name: /^Grace/ }).getByRole("cell").nth(1);
  await expect(grace).toContainText("4 units");
  await expect(grace).toContainText("7 already promised");
  await expect(table.getByRole("row", { name: /^Noor/ }).getByRole("cell").nth(1)).toContainText("10 units");
});

test("the offer rules panel fits a phone and a laptop screen", async ({ page }) => {
  for (const width of [1280, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await openDemo(page);
    await expect(panel(page).getByRole("row", { name: /^Noor/ })).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await panel(page).screenshot({ path: path.join(SCREENSHOTS, `offer-rules-${width}.png`) });
  }
});
