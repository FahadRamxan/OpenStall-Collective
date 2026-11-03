import { expect, test } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";
import { createCollectiveOrder, requestQuote } from "./support/mcp";

// A buyer agent orders through the real MCP endpoint (a small test client): request_quote, then
// create_collective_order. Reserved shares use up makers' capacity, and approve.spec.ts leaves story orders reserved in
// the same database, so each test first releases every reserved share.

/** YYYY-MM-DD, 30 days after today in UTC, the day the API counts from. */
function in30Days(): string {
  const day = new Date();
  day.setUTCDate(day.getUTCDate() + 30);
  return day.toISOString().slice(0, 10);
}

const STORY = {
  items: ["40 hand-embroidered cushion covers for corporate gifts"],
  quantity: 40,
  max_unit_price: 30,
  ship_to: "Chicago",
};

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${E2E_API_URL}/api/dev/release-reserved-shares`)).ok()).toBeTruthy();
});

test("an agent's quote becomes a draft order on /demo, whose approval page has the same totals", async ({
  page,
  request,
}) => {
  const quote = await requestQuote(request, { ...STORY, deadline: in30Days() });
  expect((quote.offers as unknown[]).length).toBe(5);
  const plan = quote.plan as { total_cost: string; lines: { quantity: number }[] };
  expect(plan.lines.map((line) => line.quantity)).toEqual([11, 12, 10, 7]);
  expect(plan.total_cost).toBe("815.00");

  const draft = await createCollectiveOrder(request, quote.request_id as string);
  expect(draft.units).toBe(40);
  expect(draft.total_usd).toBe("815.00");
  // Asked again, the same draft.
  expect((await createCollectiveOrder(request, quote.request_id as string)).order_id).toBe(draft.order_id);

  await page.goto("/demo");
  const card = page.getByRole("region", { name: "Order", exact: true });
  await expect(card).toContainText(draft.order_id as string);
  await expect(card).toContainText("40 units from 4 makers, $815.00");
  await expect(card).toContainText("Waiting for your approval");

  await card.getByRole("link", { name: "Open the approval page" }).click();
  await expect(page).toHaveURL(new RegExp(`/approve/${draft.order_id as string}$`));
  await expect(page.getByRole("heading", { name: "4 makers make it together" })).toBeVisible();
  await expect(page.getByText("$815.00").first()).toBeVisible();
  await expect(page.getByRole("region", { name: "Why this split" })).toContainText("40 units");
});
