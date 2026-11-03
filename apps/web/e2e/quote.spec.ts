import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// The story's quote (spec section 2): a buyer agent's request for 40 covers at most $30 each, every matching maker's
// agent asked side by side. Each maker's capacity decides her quantity, and approve.spec.ts leaves story orders
// reserved in the same database, so each test first releases every reserved share: then the seed table holds.
const SCREENSHOTS = path.join(__dirname, "screenshots");
const DAY = new Intl.DateTimeFormat("en-US", { month: "long", day: "numeric", year: "numeric", timeZone: "UTC" });

function requestCard(page: Page) {
  return page.getByRole("region", { name: "Request", exact: true });
}

function offers(page: Page) {
  return page.getByRole("region", { name: "Offers", exact: true });
}

/** "December 3, 2026": 30 days after today in UTC, the day the API counts to. */
function deadlineInWords(): string {
  const day = new Date();
  day.setUTCDate(day.getUTCDate() + 30);
  return DAY.format(new Date(`${day.toISOString().slice(0, 10)}T00:00:00Z`));
}

async function storyQuote(page: Page) {
  const response = await page.request.post(`${E2E_API_URL}/api/dev/quote`);
  expect(response.status()).toBe(201);
}

/** Opens /demo once the Request card has loaded the latest quote and the stream is live. */
async function openLive(page: Page) {
  const loaded = page.waitForResponse(
    (response) => response.request().method() === "GET" && new URL(response.url()).pathname === "/api/quotes",
  );
  await page.goto("/demo");
  expect((await loaded).status()).toBe(200);
  await expect(page.getByRole("status").filter({ hasText: /^Live$/ })).toBeVisible();
}

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${E2E_API_URL}/api/dev/release-reserved-shares`)).ok()).toBeTruthy();
});

test("the dev quote shows the buyer's request, and every maker's valid offer after one round", async ({ page }) => {
  await storyQuote(page);
  await openLive(page);

  const card = requestCard(page);
  await expect(card).toContainText("“40 hand-embroidered cushion covers for corporate gifts”");
  await expect(card.getByRole("list", { name: "What the buyer asked for" })).toContainText("40 units");
  await expect(card).toContainText("At most $30.00 each");
  await expect(card).toContainText(`By ${deadlineInWords()}`);
  await expect(card).toContainText("To Chicago");
  await expect(card.getByRole("status")).toHaveText(
    "Done after 1 round: 5 valid offers from 5 makers, for 54 units against 40 asked for.",
  );
  await expect(card.getByText("Offers in")).toBeVisible();

  // The four makers of the story and the backup, Noor, each with one valid offer: 12, 11, 10, 11 and 10 units.
  await expect(offers(page).getByText("Round 1 of 3")).toBeVisible();
  for (const [seller, units] of [
    ["Amina", "12"],
    ["Priya", "11"],
    ["Lucía", "10"],
    ["Grace", "11"],
    ["Noor", "10"],
  ]) {
    const valid = offers(page).getByRole("row").filter({ hasText: seller }).filter({ hasText: "Valid" });
    await expect(valid).toHaveCount(1);
    await expect(valid).toContainText(units);
  }
});

test("a new quote replaces the card's request live", async ({ page }) => {
  await openLive(page);

  await storyQuote(page);

  await expect(requestCard(page).getByRole("status")).toContainText("Done after 1 round", { timeout: 10_000 });
  await expect(offers(page).getByRole("row").filter({ hasText: "Valid" })).toHaveCount(5);
});

test("the request card fits a phone and a laptop screen", async ({ page }) => {
  await storyQuote(page);

  for (const width of [1280, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await openLive(page);
    await expect(requestCard(page).getByRole("status")).toContainText("Done after 1 round");
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await requestCard(page).screenshot({ path: path.join(SCREENSHOTS, `request-card-${width}.png`) });
  }
});
