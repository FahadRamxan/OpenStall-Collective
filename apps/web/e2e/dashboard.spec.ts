import path from "node:path";

import { expect, test } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// The AG Grid dashboard (prompt 44; spec 3.9, and 3.8's Demand Radar): orders, payouts, tracking and trust passports,
// with Radar's tip on top (spec section 2, step 13: "23 agents searched for ceramic mugs this week. Nobody sells
// them."), and a Radar group's tip sent to the maker who could make it, in her language. Sending one writes to her
// chat, so the demo world is reset afterwards.
const SCREENSHOTS = path.join(__dirname, "screenshots");

test.afterAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  expect((await api.post(`${E2E_API_URL}/api/demo/reset`)).ok()).toBeTruthy();
  await api.dispose();
});

test("the dashboard's tables, and Demand Radar's tip sent to the maker who could make it", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { level: 1, name: "Dashboard" })).toBeVisible();

  const tip = page.getByRole("region", { name: "Demand Radar tip" });
  await expect(tip).toContainText(/\d+ agents searched for ceramic mugs this week\. Nobody sells them\./);
  await expect(page.getByRole("region", { name: "Orders" }).getByRole("link", { name: "ord_demo" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Payouts" })).toContainText("Amina");
  const passports = page.getByRole("region", { name: "Trust passports" });
  await expect(passports.getByText("Valid", { exact: true })).toHaveCount(5);
  await expect(passports.getByRole("link", { name: "Priya" })).toBeVisible();

  const radar = page.getByRole("region", { name: "Demand Radar", exact: true });
  await expect(radar).toContainText("embroidered table runner");
  await expect(radar).toContainText("Nobody on OpenStall yet");
  await radar.getByRole("button", { name: "Send the tip to Noor" }).click();
  await expect(radar.getByText(/^Tipped /)).toBeVisible();
  await page.screenshot({ path: path.join(SCREENSHOTS, "dashboard-radar-1280.png"), fullPage: false });

  // Noor has it in her chat, in Urdu.
  await page.goto("/seller-chat?seller=s_noor");
  await expect(page.getByText("OpenStall ڈیمانڈ ریڈار").first()).toBeVisible();
});
