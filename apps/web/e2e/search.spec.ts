import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { connect, searchProducts } from "./support/mcp";

// A buyer agent searches through the real MCP endpoint (a small test client), and /demo shows each search live.
// Earlier spec files reserve and pay story orders in the same database, which uses up makers' capacity, so these
// tests never count on what a maker has left: only on what each search found and how /demo shows it.
const SCREENSHOTS = path.join(__dirname, "screenshots");
const DAY = new Intl.DateTimeFormat("en-US", { month: "long", day: "numeric", year: "numeric", timeZone: "UTC" });

function searches(page: Page) {
  return page.getByRole("list", { name: "Agent searches, newest first" });
}

/** The panel's load of the earlier searches: start waiting before the page opens. */
function searchesLoaded(page: Page) {
  return page.waitForResponse(
    (response) => response.request().method() === "GET" && new URL(response.url()).pathname === "/api/searches",
  );
}

/** Opens /demo and waits until the panel has loaded the earlier searches and the stream is live. */
async function openLive(page: Page) {
  const loaded = searchesLoaded(page);
  await page.goto("/demo");
  expect((await loaded).status()).toBe(200);
  await expect(page.getByRole("status").filter({ hasText: /^Live$/ })).toBeVisible();
}

/** YYYY-MM-DD, this many days after today in UTC, the day the API counts from. */
function daysFromToday(days: number): string {
  const day = new Date();
  day.setUTCDate(day.getUTCDate() + days);
  return day.toISOString().slice(0, 10);
}

/** "December 3, 2026", as the panel and the feed write a date. */
function inWords(isoDate: string): string {
  return DAY.format(new Date(`${isoDate}T00:00:00Z`));
}

test("a buyer agent's search appears live on /demo, and a ceramic mugs search shows as zero results", async ({
  page,
  request,
}) => {
  expect(await connect(request)).toContain("search_products");
  await openLive(page);
  const deadline = daysFromToday(30);
  const searchedAt = Date.now();

  const found = await searchProducts(request, "ceramic mugs", {
    max_price: 12,
    quantity: 40,
    deadline,
    ship_to: "Chicago",
  });

  expect(found).toEqual([]);
  const newest = searches(page).getByRole("listitem").first();
  // The newest row is this search, streamed in after the page opened (the API and the test share one clock).
  await expect
    .poll(async () => Date.parse((await newest.locator("time").getAttribute("datetime")) ?? ""), { timeout: 3_000 })
    .toBeGreaterThanOrEqual(searchedAt - 1_000);
  await expect(newest).toContainText("“ceramic mugs”");
  await expect(newest).toContainText("No results");
  await expect(newest).toContainText(`At most $12.00 each · 40 units · By ${inWords(deadline)} · To Chicago`);
  // Amber: the warning colour behind the whole row, as well as the words.
  await expect(newest).toHaveAttribute("data-results", "none");
  await expect(newest).toHaveCSS("background-color", "rgb(253, 243, 215)");
  // The live feed says it in plain words too, with the buyer's own words in quotes.
  await expect(page.getByRole("list", { name: "Activity, newest first" }).getByRole("listitem").first()).toContainText(
    `An agent searched for "ceramic mugs" (at most $12.00 each, 40 units, by ${inWords(deadline)}, to "Chicago"): ` +
      "no results.",
  );
  // Screen readers hear the new search too.
  await expect(page.getByRole("region", { name: "Agent searches" }).getByRole("status")).toHaveText(
    "New search for “ceramic mugs”: no results.",
  );
});

test("a search that finds covers shows its count, and /demo shows earlier searches when it opens", async ({
  page,
  request,
}) => {
  const found = await searchProducts(request, "embroidered cushion covers", { max_price: 20, ship_to: "Chicago" });

  // At most $20: Priya's $16 and Amina's $18 covers, cheapest first, each with her trust record and the demo label.
  expect(found.map((item) => item.seller_name)).toEqual(["Priya", "Amina"]);
  for (const item of found) {
    expect(item.data_source).toBe("seeded_demo");
    expect(item.trust?.summary).toMatch(/^Trust score 0\.\d\d from \d+ delivered orders: .*\(seeded demo numbers\)$/);
    expect(item.deadline).toBe(daysFromToday(30));
    expect(item.capacity_by_deadline).toBeGreaterThanOrEqual(0);
  }

  // The page's event backlog also carries this search, so check that the load itself answered.
  const loaded = searchesLoaded(page);
  await page.goto("/demo");
  const response = await loaded;
  expect(response.status()).toBe(200);
  expect(((await response.json()) as { query: string }[])[0].query).toBe("embroidered cushion covers");

  const newest = searches(page).getByRole("listitem").first();
  await expect(newest).toContainText("“embroidered cushion covers”");
  await expect(newest).toContainText("At most $20.00 each · To Chicago");
  await expect(newest).toContainText("2 results");
  await expect(newest).not.toContainText("No results");
  await expect(newest).toHaveAttribute("data-results", "some");
  await expect(page.getByRole("region", { name: "Agent searches" }).getByRole("alert")).toHaveCount(0);
  // Searches loaded when the page opens are not read out as new.
  await expect(page.getByRole("region", { name: "Agent searches" }).getByRole("status")).toBeEmpty();
});

test("the searches panel fits a phone and a laptop screen", async ({ page, request }) => {
  await searchProducts(request, "hand-embroidered cushion covers for corporate gifts", {
    max_price: 30,
    ship_to: "Chicago",
  });
  await searchProducts(request, "ceramic mugs", { quantity: 40, deadline: daysFromToday(30), ship_to: "Chicago" });

  for (const width of [1280, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await openLive(page);
    await expect(searches(page).getByRole("listitem").first()).toContainText("“ceramic mugs”");
    await expect(searches(page).getByRole("listitem").nth(1)).toContainText("corporate gifts");
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page
      .getByRole("region", { name: "Agent searches" })
      .screenshot({ path: path.join(SCREENSHOTS, `agent-searches-${width}.png`) });
    await page.screenshot({ path: path.join(SCREENSHOTS, `demo-searches-${width}.png`) });
  }
});
