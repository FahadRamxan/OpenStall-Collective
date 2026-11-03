import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// Fake mode's seller agents answer the story's request (40 covers, at most $30 each): Grace's agent asks her $32 list
// price, the code refuses it as over the buyer's maximum, and it comes back at $29. Each maker's capacity decides how
// many she offers, and approve.spec.ts leaves story orders reserved, so each test first releases every reserved share.
const SCREENSHOTS = path.join(__dirname, "screenshots");

function offers(page: Page) {
  return page.getByRole("region", { name: "Offers", exact: true });
}

/** A row of the offers grid, by the seller and the price it shows. */
function offerRow(page: Page, seller: string, price: string) {
  return offers(page).getByRole("row").filter({ hasText: seller }).filter({ hasText: price });
}

async function storyOffers(page: Page): Promise<string> {
  const response = await page.request.post(`${E2E_API_URL}/api/dev/story-offers`);
  expect(response.status()).toBe(201);
  return ((await response.json()) as { request_id: string }).request_id;
}

/** Opens /demo once the offers panel has loaded the earlier offers and the stream is live. */
async function openLive(page: Page) {
  const loaded = page.waitForResponse(
    (response) => response.request().method() === "GET" && new URL(response.url()).pathname === "/api/offers",
  );
  await page.goto("/demo");
  expect((await loaded).status()).toBe(200);
  await expect(page.getByRole("status").filter({ hasText: /^Live$/ })).toBeVisible();
}

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${E2E_API_URL}/api/dev/release-reserved-shares`)).ok()).toBeTruthy();
});

test("Grace's agent offers $32, the code refuses it as over the buyer's maximum, and her $29 is valid", async ({
  page,
}) => {
  await storyOffers(page);
  await openLive(page);

  const refused = offerRow(page, "Grace", "$32.00");
  await expect(refused).toContainText("Refused");
  await expect(refused).toContainText("over the buyer's maximum of $30.00");
  await expect(refused).toContainText("Round 1");
  const valid = offerRow(page, "Grace", "$29.00");
  await expect(valid).toContainText("Valid");
  await expect(valid).toContainText("Round 1, try 2");
  await expect(valid).toContainText("11");
  await expect(valid).toContainText("Grace can make 11");
  // The other makers' first prices are within their limits and the buyer's maximum.
  await expect(offerRow(page, "Amina", "$18.00")).toContainText("Valid");
  await expect(offerRow(page, "Noor", "$29.50")).toContainText("Valid");
  await expect(offers(page).getByRole("alert")).toHaveCount(0);
});

test("offers appear live on /demo as the code checks them", async ({ page }) => {
  await openLive(page);

  await storyOffers(page);

  await expect(offerRow(page, "Grace", "$29.00")).toContainText("Valid");
  await expect(offerRow(page, "Grace", "$32.00")).toContainText("Refused");
  // Only the latest request's offers: one row per proposal, seven in all.
  await expect(offers(page).getByRole("row").filter({ hasText: /\$\d/ })).toHaveCount(7);
});

test("the offers panel fits a phone and a laptop screen", async ({ page }) => {
  await storyOffers(page);

  for (const width of [1280, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await openLive(page);
    await expect(offerRow(page, "Grace", "$29.00")).toBeVisible();
    // The grid scrolls sideways inside itself on a phone; the page never does.
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await offers(page).screenshot({ path: path.join(SCREENSHOTS, `offers-${width}.png`) });
  }
});
