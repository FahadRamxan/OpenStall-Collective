import { expect, test } from "@playwright/test";

// An address no route matches. (A wrong stall id has its own "No stall here" page: see stall.spec.ts.)
const MISSING = "/no-such-page";

test("an unknown address gets a 404 page in the site's own layout", async ({ page }) => {
  const response = await page.goto(MISSING);

  expect(response?.status()).toBe(404);
  await expect(page).toHaveTitle("Page not found · OpenStall Collective");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Page not found");
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await expect(page.getByRole("contentinfo").getByText("No real money moves: PayPal's sandbox, or simulated PayPal in test mode.")).toBeVisible();
});

test("the 404 page uses the site's colours and font, not Next.js's defaults", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto(MISSING);

  // --background in globals.css: #f8f6f1.
  await expect(page.locator("body")).toHaveCSS("background-color", "rgb(248, 246, 241)");
  await expect(page.getByRole("heading", { level: 1 })).toHaveCSS("font-family", /Geist/);
});

test("on a phone, the 404 page is short enough to show the footer", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(MISSING);

  await expect(page.getByRole("contentinfo")).toBeInViewport();
});

test('"Go to the home page" goes home', async ({ page }) => {
  await page.goto(MISSING);
  await page.getByRole("link", { name: "Go to the home page" }).click();

  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Many small makers. One big order. One PayPal checkout.",
  );
});
