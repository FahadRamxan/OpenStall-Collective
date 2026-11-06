import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// A materials advance (prompt 37). After the story's order is approved, Grace asks on her phone for an advance: her
// signed trust score earns a quarter of her share, which OpenStall pays ahead (simulated PayPal here), not the buyer.
// When she ships, her share is captured whole and she is paid the rest. Earlier spec files leave story orders
// reserved, so the test first releases them.
const SCREENSHOTS = path.join(__dirname, "screenshots");

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${E2E_API_URL}/api/dev/release-reserved-shares`)).ok()).toBeTruthy();
});

function phone(page: Page, name: string) {
  return page.getByRole("article", { name: `${name}'s phone` });
}

test("Grace asks for an advance: OpenStall pays a quarter ahead, and the rest when she ships", async ({ page }) => {
  test.setTimeout(60_000); // the whole story to her payment: approval, the advance, then her receipt
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/demo");
  await expect(page.getByRole("status").filter({ hasText: /^Live$/ })).toBeVisible();
  const controls = page.getByRole("region", { name: "Run the story" });
  await controls.getByRole("button", { name: "Run the demo request" }).click();
  await expect(controls.getByRole("status")).toContainText("drafted: $815.00");
  await controls.getByRole("link", { name: "Open its approval page" }).click();
  await page.getByRole("button", { name: "Approve and pay with PayPal" }).click();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Simulated PayPal is holding $815.00" })).toBeVisible();

  await page.goto("/demo");
  const grace = phone(page, "Grace");
  await grace.getByRole("button", { name: /Grace asks for an advance/ }).click();
  await expect(grace).toContainText("Yes: your trust record lets OpenStall pay you $50.75 now for materials");
  await grace.getByRole("button", { name: /Reply\s*“\s*Yes\s*”\s*as Grace/ }).click();
  await expect(grace).toContainText("Your advance of $50.75 for materials has been sent to your Venmo account.");

  const payments = page.getByRole("region", { name: "Payments" });
  const row = payments.getByRole("list", { name: "Each maker's payment" }).getByRole("listitem").filter({ hasText: "Grace" });
  await expect(row).toContainText("Advance for materials: $50.75, paid by OpenStall (simulated PayPal), not the buyer");
  await expect(page.getByRole("region", { name: "Live activity" })).toContainText(
    "OpenStall paid Grace a $50.75 advance for materials",
  );
  await page.screenshot({ path: path.join(SCREENSHOTS, "advance-1280.png"), fullPage: false });

  // She ships: her share is captured whole, and she is paid the rest.
  await grace.getByRole("button", { name: /Send Grace's courier receipt/ }).click();
  await grace.getByRole("button", { name: /Reply\s*“\s*Yes\s*”\s*as Grace/ }).click();
  await expect(grace).toContainText("You are paid! $152.25 for order");
  await expect(row).toContainText("Paid on proof of shipping");
});
