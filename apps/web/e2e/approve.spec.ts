import { expect, test } from "@playwright/test";

// playwright.config.ts seeds the story's draft order as ord_demo (scripts/seed_demo.py --demo-order).
const DEMO_ORDER = "/approve/ord_demo";
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
  await expect(page.getByRole("button", { name: "Approve and pay with PayPal" })).toBeDisabled();
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
