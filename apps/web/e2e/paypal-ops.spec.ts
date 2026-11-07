import path from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// The PayPal ops agent (prompt 55), in test mode: on /dashboard, the latest order is checked against PayPal through
// PayPal's MCP server (test mode's stand-in, which says so), line by line, and the ops agent answers a question from the
// server's read tools. It is offered no tool that changes anything at PayPal.
const SCREENSHOTS = path.join(__dirname, "screenshots");

async function freshOrder(request: APIRequestContext): Promise<string> {
  expect((await request.post(`${E2E_API_URL}/api/dev/release-reserved-shares`)).status()).toBe(200);
  const response = await request.post(`${E2E_API_URL}/api/dev/story-orders`);
  expect(response.status()).toBe(201);
  return ((await response.json()) as { order_id: string }).order_id;
}

async function approveAndPayPriya(page: Page, orderId: string) {
  await page.goto(`/approve/${orderId}`);
  await page.getByRole("button", { name: "Approve and pay with PayPal" }).click();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Simulated PayPal is holding $815.00" })).toBeVisible();
  const priya = page.getByRole("list", { name: "Each maker's share" }).getByRole("listitem").filter({ hasText: "Priya" });
  await priya.getByRole("button", { name: /Simulate proof of shipping/ }).click();
  await expect(priya).toContainText("Paid on proof of shipping");
}

test("the latest order is checked against PayPal through its MCP server, and the ops agent answers", async ({
  page,
  request,
}) => {
  const orderId = await freshOrder(request);
  await approveAndPayPriya(page, orderId);

  await page.goto("/dashboard");
  const panel = page.getByRole("region", { name: "PayPal ops agent" });
  await expect(panel).toContainText("Test mode's stand-in for PayPal's MCP server.");
  await expect(panel).toContainText("Never offered: 3 tools that change something at PayPal");
  await expect(panel).toContainText("create_refund");

  await panel.getByRole("button", { name: "Check the latest order with PayPal" }).click();
  await expect(panel).toContainText(`Order ${orderId}: PayPal agrees on every line.`);
  const lines = panel.getByRole("list", { name: "OpenStall beside PayPal" }).getByRole("listitem");
  await expect(lines.filter({ hasText: "The amount" })).toContainText("OpenStall: $815.00. PayPal: $815.00.");
  await expect(lines.filter({ hasText: "Priya's capture" })).toContainText("Agrees");
  await expect(lines.filter({ hasText: "Priya's tracking" })).toContainText("PayPal: on the order.");

  await panel.getByRole("button", { name: "Ask the ops agent" }).click();
  const read = panel.getByRole("list", { name: "What the agent read" }).getByRole("listitem");
  await expect(read).toHaveCount(2);
  await expect(read.first()).toContainText("get_order");
  await expect(panel).toContainText("Test mode's stand-in for the ops agent: PayPal says order FAKE-");
  await expect(panel).toContainText("with 1 capture ($176.00 taken)");
  await page.screenshot({ path: path.join(SCREENSHOTS, "paypal-ops-1280.png"), fullPage: true });
});
