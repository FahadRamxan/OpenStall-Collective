import { expect, test } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";
import { checkout, createCollectiveOrder, getOrderStatus, requestQuote } from "./support/mcp";

// A buyer agent orders through the real MCP endpoint and gets the approval link for its human; the human approves at
// the simulated PayPal page; the agent then sees the money reserved. Reserved shares use up makers' capacity, and
// earlier spec files leave story orders reserved in the same database, so the test first releases every reserved share.

/** YYYY-MM-DD, 30 days after today in UTC, the day the API counts from. */
function in30Days(): string {
  const day = new Date();
  day.setUTCDate(day.getUTCDate() + 30);
  return day.toISOString().slice(0, 10);
}

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${E2E_API_URL}/api/dev/release-reserved-shares`)).ok()).toBeTruthy();
});

test("tools, then the approval link, then the simulated PayPal approval, and the agent sees it reserved", async ({
  page,
  request,
}) => {
  const quote = await requestQuote(request, {
    items: ["40 hand-embroidered cushion covers for corporate gifts"],
    quantity: 40,
    max_unit_price: 30,
    deadline: in30Days(),
    ship_to: "Chicago",
  });
  const draft = await createCollectiveOrder(request, quote.request_id as string);
  const orderId = draft.order_id as string;
  const link = await checkout(request, orderId);
  expect(link.approval_url).toMatch(new RegExp(`/approve/${orderId}$`));
  expect((await getOrderStatus(request, orderId)).status).toBe("draft");

  await page.goto("/demo");
  const card = page.getByRole("region", { name: "Order", exact: true });
  await expect(card).toContainText(orderId);
  await expect(card).toContainText("Approval link sent to the human");
  await expect(card.getByRole("link", { name: link.approval_url as string })).toBeVisible();

  // The human opens the link: the approval page says an agent asked for the order.
  await page.goto(new URL(link.approval_url as string).pathname);
  await expect(page.getByText("Requested by an AI agent")).toBeVisible();
  await page.getByRole("button", { name: "Approve and pay with PayPal" }).click();
  await expect(page).toHaveURL(/\/fake-paypal\?token=FAKE-[0-9A-F]+$/);
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Simulated PayPal is holding $815.00" })).toBeVisible();

  const status = await getOrderStatus(request, orderId);
  expect(status.status).toBe("authorized");
  expect(status.approved).toBe(true);
  expect(new Set((status.shares as { status: string }[]).map((share) => share.status))).toEqual(
    new Set(["authorized"]),
  );
});
