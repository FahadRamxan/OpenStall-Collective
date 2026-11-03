import { expect, test } from "@playwright/test";

const HEADLINE = "Many small makers. One big order. One PayPal checkout.";

// Cache Components keeps pages you navigated away from in the DOM, hidden. getByRole skips hidden
// elements, so these tests find things by role rather than by CSS selector.

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("shows the headline", async ({ page }) => {
  await expect(page).toHaveTitle("OpenStall Collective");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(HEADLINE);
});

test('"See the live demo" goes to /demo', async ({ page }) => {
  await page.getByRole("link", { name: "See the live demo" }).click();

  await expect(page).toHaveURL("/demo");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Live demo");
  await expect(page.getByRole("heading", { name: "Live activity" })).toBeVisible();
});

test("the footer says it runs in the PayPal sandbox", async ({ page }) => {
  await expect(page.getByRole("contentinfo").getByText("Runs in the PayPal sandbox. No real money moves.")).toBeVisible();
});

test("the header links reach every page and mark the current one", async ({ page }) => {
  const nav = page.getByRole("navigation", { name: "Main" });
  const stops = [
    { link: "Demo", url: "/demo", heading: "Live demo" },
    { link: "Seller chat", url: "/seller-chat", heading: "Seller chat" },
    { link: "Dashboard", url: "/dashboard", heading: "Dashboard" },
    { link: "Home", url: "/", heading: HEADLINE },
  ];

  for (const { link, url, heading } of stops) {
    await nav.getByRole("link", { name: link }).click();

    await expect(page).toHaveURL(url);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(heading);
    await expect(nav.getByRole("link", { name: link })).toHaveAttribute("aria-current", "page");
  }
});

test("the footer shows the browser can reach the API", async ({ page }) => {
  // Proves NEXT_PUBLIC_API_BASE_URL and the API's CORS setting (WEB_BASE_URL) fit together.
  await expect(page.getByRole("contentinfo").getByRole("status")).toHaveText("API online");
});
