import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

// The PayPal doctor and the PayPal products table on /status (prompt 53). Test mode: nothing reaches PayPal, and the
// APIMatic cross-check still runs, on the repository's paypal-plan.md, the gateway's code and the installed SDK.
const SCREENSHOTS = path.join(__dirname, "screenshots");

function product(page: Page, name: string) {
  return page
    .getByRole("table", { name: "PayPal products" })
    .getByRole("row")
    .filter({ has: page.getByRole("rowheader", { name }) });
}

test("the PayPal doctor checks the setup, and each PayPal product says how far it has got", async ({ page }) => {
  await page.goto("/status");

  const checks = page.getByRole("list", { name: "PayPal checks" });
  await expect(checks.getByRole("listitem")).toHaveCount(8);
  await expect(checks.getByRole("listitem").first()).toHaveText(
    "OKWhere the money goesTest mode: a simulated PayPal. Nothing reaches PayPal and no money moves.",
  );
  await expect(checks.getByRole("listitem").filter({ hasText: "PayPal keys and token" })).toContainText("Skipped");
  for (const check of [
    "Every SDK call has its row in the plan",
    "Each call passes the keywords the plan says",
    "The installed SDK has every planned operation",
    "The plan, the pin and the installed SDK are one commit",
  ]) {
    await expect(checks.getByRole("listitem").filter({ hasText: `APIMatic cross-check: ${check}` })).toContainText("OK");
  }
  await expect(page.getByText("Nothing failed.", { exact: true })).toBeVisible();

  await expect(product(page, "Orders v2, intent AUTHORIZE")).toContainText("Proven on the sandbox");
  await expect(product(page, "Orders v2, intent AUTHORIZE")).toContainText("POST /v2/checkout/orders");
  await expect(product(page, "Order tracking")).toContainText("Built, not yet run on the sandbox");
  await expect(product(page, "Payouts to Venmo")).toContainText("Simulated");
  await expect(product(page, "Hyperwallet")).toContainText("Simulated");
  await expect(product(page, "Disputes")).toContainText("Built, not yet run on the sandbox");
  await expect(product(page, "Braintree")).toContainText("Not built yet");
  await page.screenshot({ path: path.join(SCREENSHOTS, "paypal-doctor-1280.png"), fullPage: true });

  await page.setViewportSize({ width: 375, height: 812 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: path.join(SCREENSHOTS, "paypal-doctor-375.png"), fullPage: true });
});

test("the home page links to the PayPal products", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Every PayPal product, and how far it has got" }).click();

  await expect(page).toHaveURL("/status#paypal-products");
  await expect(page.getByRole("heading", { level: 2, name: "PayPal products" })).toBeVisible();
  await expect(product(page, "Hyperwallet")).toBeVisible();
});
