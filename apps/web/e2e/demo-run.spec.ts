import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// The "Run the demo request" button: the scripted buyer agent plays the story through the MCP storefront, the
// stepper follows it to Approval, and the approval page pays in fake mode. Reserved shares use up makers' capacity,
// and earlier spec files leave story orders reserved, so each test first releases every reserved share.
const SCREENSHOTS = path.join(__dirname, "screenshots");

function controls(page: Page) {
  return page.getByRole("region", { name: "Run the story" });
}

function step(page: Page, name: string) {
  return controls(page).getByRole("list", { name: "The buyer agent's steps" }).getByRole("listitem").filter({ hasText: name });
}

async function openLive(page: Page) {
  await page.goto("/demo");
  await expect(page.getByRole("status").filter({ hasText: /^Live$/ })).toBeVisible();
}

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${E2E_API_URL}/api/dev/release-reserved-shares`)).ok()).toBeTruthy();
});

test("Run walks the stepper to Approval, and the approval link pays in fake mode", async ({ page }) => {
  await openLive(page);

  await controls(page).getByRole("button", { name: "Run the demo request" }).click();

  for (const name of ["Search", "Quote", "Offers", "Allocation", "Approval"]) {
    await expect(step(page, name)).toHaveAttribute("data-state", "done");
  }
  await expect(controls(page).getByRole("status")).toContainText("drafted: $815.00");
  await expect(page.getByRole("region", { name: "Allocation", exact: true })).toContainText("All 40 from 4 makers");
  await controls(page).screenshot({ path: path.join(SCREENSHOTS, "demo-controls-1280.png") });

  await controls(page).getByRole("link", { name: "Open its approval page" }).click();
  await expect(page.getByText("Requested by an AI agent")).toBeVisible();
  await page.getByRole("button", { name: "Approve and pay with PayPal" }).click();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Simulated PayPal is holding $815.00" })).toBeVisible();
});

test("Reset asks first, then puts the demo world back and the stepper starts over", async ({ page }) => {
  await openLive(page);
  await controls(page).getByRole("button", { name: "Run the demo request" }).click();
  await expect(step(page, "Approval")).toHaveAttribute("data-state", "done");

  await controls(page).getByRole("button", { name: "Reset demo" }).click();
  const confirm = controls(page).getByRole("group", { name: "Confirm the reset" });
  await expect(confirm).toContainText("Remove every order, quote and offer?");
  await confirm.getByRole("button", { name: "Cancel" }).click();
  await expect(confirm).toHaveCount(0);

  await controls(page).getByRole("button", { name: "Reset demo" }).click();
  await controls(page).getByRole("button", { name: "Yes, reset" }).click();

  await expect(controls(page).getByRole("status")).toContainText("The demo is reset");
  await expect(step(page, "Search")).toHaveAttribute("data-state", "waiting");
  await expect(page.getByRole("region", { name: "Live activity" })).toContainText("The demo was reset");
});

test("the controls fit a phone screen", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await openLive(page);
  await expect(controls(page).getByRole("button", { name: "Run the demo request" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await controls(page).screenshot({ path: path.join(SCREENSHOTS, "demo-controls-375.png") });
});
