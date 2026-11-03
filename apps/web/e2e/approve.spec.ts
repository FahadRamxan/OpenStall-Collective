import path from "node:path";

import { expect, test, type APIRequestContext } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// playwright.config.ts seeds the story's draft order as ord_demo (scripts/seed_demo.py --demo-order). Tests that pay
// make a fresh copy of it, so ord_demo always stays a draft, however often or in whatever order the tests run.
const DEMO_ORDER = "/approve/ord_demo";
const SCREENSHOTS = path.join(__dirname, "screenshots");
const SHARES = [
  { name: "Amina", line: "12 × $18.00", amount: "$216.00" },
  { name: "Priya", line: "11 × $16.00", amount: "$176.00" },
  { name: "Lucía", line: "10 × $22.00", amount: "$220.00" },
  { name: "Grace", line: "7 × $29.00", amount: "$203.00" },
];

test("the story's order shows four makers, 12/11/10/7, and the $815.00 total", async ({ page }) => {
  await page.goto(DEMO_ORDER);

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Approve this order");
  await expect(page.getByRole("region", { name: "What your AI agent asked for" })).toContainText(
    "40 hand-embroidered cushion covers for corporate gifts",
  );
  const shares = page.getByRole("list", { name: "Each maker's share" }).getByRole("listitem");
  await expect(shares).toHaveCount(4);
  for (const [index, share] of SHARES.entries()) {
    await expect(shares.nth(index)).toContainText(share.name);
    await expect(shares.nth(index)).toContainText(share.line);
    await expect(shares.nth(index)).toContainText(share.amount);
  }
  await expect(page.getByText("40 items from 4 makers")).toBeVisible();
  await expect(page.getByText("$815.00", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve and pay with PayPal" })).toBeEnabled();
});

async function freshOrder(request: APIRequestContext): Promise<string> {
  const response = await request.post(`${E2E_API_URL}/api/dev/story-orders`);
  expect(response.status()).toBe(201);
  return ((await response.json()) as { order_id: string }).order_id;
}

test("Approve goes to the simulated PayPal page, and approving there comes back to OpenStall", async ({
  page,
  request,
}) => {
  const orderId = await freshOrder(request);
  await page.goto(`/approve/${orderId}`);

  await page.getByRole("button", { name: "Approve and pay with PayPal" }).click();

  await expect(page).toHaveURL(/\/fake-paypal\?token=FAKE-[0-9A-F]+$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Simulated PayPal (test mode)");
  await expect(page.getByRole("note")).toContainText("No PayPal account is used and no money moves.");
  await expect(page.getByText("$815.00", { exact: true })).toBeVisible();
  await expect(page.getByRole("list", { name: "What you approve" }).getByRole("listitem")).toHaveCount(4);
  await page.screenshot({ path: path.join(SCREENSHOTS, "fake-paypal-1280.png"), fullPage: true });

  await page.getByRole("button", { name: "Approve", exact: true }).click();

  await expect(page).toHaveURL(new RegExp(`/approve/${orderId}/return\\?token=FAKE-[0-9A-F]+&PayerID=FAKEBUYER01$`));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("You approved the order at PayPal");
});

test("leaving the simulated PayPal page comes back calmly, and Try again returns to it", async ({
  page,
  request,
}) => {
  const orderId = await freshOrder(request);
  await page.goto(`/approve/${orderId}`);
  await page.getByRole("button", { name: "Approve and pay with PayPal" }).click();

  await page.getByRole("button", { name: "Cancel and go back" }).click();

  await expect(page).toHaveURL(`/approve/${orderId}?cancelled=1`);
  const notice = page.getByRole("status").filter({ hasText: "You left PayPal before approving" });
  await expect(notice).toContainText("Nothing was reserved and nothing was taken.");
  await notice.getByRole("button", { name: "Try again" }).click();
  await expect(page).toHaveURL(/\/fake-paypal\?token=FAKE-[0-9A-F]+$/);
});

test("a maker's name on the order opens her stall", async ({ page }) => {
  await page.goto(DEMO_ORDER);

  await page.getByRole("link", { name: "Grace" }).click();

  await expect(page).toHaveURL("/stall/s_grace");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Grace");
});

test("an unknown order says so", async ({ page }) => {
  await page.goto("/approve/ord_nobody");

  await expect(page.getByRole("heading", { name: "No order here" })).toBeVisible();
});

test("the approval page fits a phone and a laptop screen", async ({ page }) => {
  for (const width of [375, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(DEMO_ORDER);
    await expect(page.getByRole("list", { name: "Each maker's share" }).getByRole("listitem")).toHaveCount(4);
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({ path: `e2e/screenshots/approve-${width}.png`, fullPage: true });
  }
});
