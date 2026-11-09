import path from "node:path";

import { expect, test, type APIRequestContext } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// Venmo at the approval (prompt 57), in test mode: the person approves the story's order with Venmo instead of
// PayPal's checkout. The order is made for Venmo, approved on the simulated Venmo page, and then reserved like any
// order; the receipt says it was approved with Venmo, and that it is simulated.
const SCREENSHOTS = path.join(__dirname, "screenshots");

async function freshOrder(request: APIRequestContext): Promise<string> {
  expect((await request.post(`${E2E_API_URL}/api/dev/release-reserved-shares`)).status()).toBe(200);
  const response = await request.post(`${E2E_API_URL}/api/dev/story-orders`);
  expect(response.status()).toBe(201);
  return ((await response.json()) as { order_id: string }).order_id;
}

test("a person approves the story's order with Venmo, and PayPal holds it the same way", async ({ page, request }) => {
  const orderId = await freshOrder(request);

  await page.goto(`/approve/${orderId}`);
  await expect(page.getByText("Or pay with Venmo")).toBeVisible();
  await page.getByRole("button", { name: "Pay with simulated Venmo" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Simulated Venmo (test mode)" })).toBeVisible();
  await expect(page.getByRole("note")).toContainText("This page stands in for Venmo");
  await expect(page.getByText(`asks you to approve order ${orderId} with Venmo.`)).toBeVisible();
  await page.getByRole("button", { name: "Approve", exact: true }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Simulated PayPal is holding $815.00" })).toBeVisible();
  await expect(page.getByText("Approved with Venmo (simulated)", { exact: false })).toBeVisible();
  const shares = page.getByRole("list", { name: "Each maker's share" }).getByRole("listitem");
  await expect(shares).toHaveCount(4);
  await expect(shares.first()).toContainText("Reserved, paid when she ships");
  await page.screenshot({ path: path.join(SCREENSHOTS, "venmo-receipt-1280.png"), fullPage: true });

  const order = await (await request.get(`${E2E_API_URL}/api/orders/${orderId}`)).json();
  expect(order.paid_with).toBe("venmo");
});
