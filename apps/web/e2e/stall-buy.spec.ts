import path from "node:path";

import { expect, test } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// PayPal buttons on the stall page (prompt 42; spec 3.9: "a seller's public page with PayPal buttons for human
// buyers"). In test mode there is no PayPal to load, so a simulated PayPal button takes the person to the simulated
// PayPal page; the order is then reserved like any other, and the maker is told where it ships. The purchase uses up
// some of Priya's capacity, so the demo world is reset afterwards.
const SCREENSHOTS = path.join(__dirname, "screenshots");

test.afterAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  expect((await api.post(`${E2E_API_URL}/api/demo/reset`)).ok()).toBeTruthy();
  await api.dispose();
});

test("a person buys from Priya's stall with simulated PayPal, and Priya is told where it ships", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/stall/s_priya");
  const buy = page.getByRole("region", { name: "Buy from Priya" });
  await expect(buy).toContainText("PayPal only reserves the money.");

  await buy.getByLabel("How many").fill("2");
  await buy.getByLabel("Ship to (city)").fill("Chicago");
  await expect(buy).toContainText("2 × $16.00 = $32.00, worked out again by OpenStall");
  await buy.scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(SCREENSHOTS, "stall-buy-1280.png"), fullPage: false });
  await buy.getByRole("button", { name: /Buy with simulated PayPal/ }).click();

  // The simulated PayPal page, then the receipt: the money is held, and Priya is told.
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Simulated PayPal is holding $32.00" })).toBeVisible();
  await expect(page.getByText("Each maker has been told about her share, in her own language.")).toBeVisible();
  await expect(page.getByRole("list", { name: "Each maker's share" })).toContainText("Priya");

  await page.goto("/seller-chat?seller=s_priya");
  await expect(page.getByText(/Chicago/).first()).toBeVisible();
});
