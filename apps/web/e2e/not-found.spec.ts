import { expect, test } from "@playwright/test";

// Stall pages do not exist yet, so a stall link is the most likely way to reach this page today.
const MISSING = "/stall/does-not-exist";

test("an unknown address gets a 404 page in the site's own layout", async ({ page }) => {
  const response = await page.goto(MISSING);

  expect(response?.status()).toBe(404);
  await expect(page).toHaveTitle("Page not found · OpenStall Collective");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Page not found");
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await expect(page.getByRole("contentinfo").getByText("Runs in the PayPal sandbox. No real money moves.")).toBeVisible();
});

test("the 404 page uses the site's colours and font, not Next.js's defaults", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto(MISSING);

  // --background in globals.css: #faf8f5.
  await expect(page.locator("body")).toHaveCSS("background-color", "rgb(250, 248, 245)");
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
    "Small sellers on WhatsApp, selling to AI shopping agents",
  );
});
