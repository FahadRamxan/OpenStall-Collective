import path from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";
import { connect, getOrderStatus, getTrustCard } from "./support/mcp";

// Delivery and the end of an order (prompt 34): on the receipt, the buyer confirms each parcel that shipped has
// arrived; the maker is told in her language, the live feed and the buyer's agent follow it, and the order completes
// with its last parcel. Amina does not ship in this story, so her share is released. Each
// maker's trust passport is then signed again with the delivery counted (prompt 36).
const SCREENSHOTS = path.join(__dirname, "screenshots");

async function freshOrder(request: APIRequestContext): Promise<string> {
  const response = await request.post(`${E2E_API_URL}/api/dev/story-orders`);
  expect(response.status()).toBe(201);
  return ((await response.json()) as { order_id: string }).order_id;
}

async function approveAtSimulatedPayPal(page: Page, orderId: string) {
  await page.goto(`/approve/${orderId}`);
  await page.getByRole("button", { name: "Approve and pay with PayPal" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Simulated PayPal (test mode)");
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Simulated PayPal is holding $815.00" })).toBeVisible();
}

// The test below signs makers' passports again with their deliveries. Put the demo world back as seeded afterwards:
// later spec files read the seeded passports.
test.afterAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  expect((await api.post(`${E2E_API_URL}/api/demo/reset`)).ok()).toBeTruthy();
  await api.dispose();
});

function row(page: Page, name: string) {
  return page.getByRole("list", { name: "Each maker's share" }).getByRole("listitem").filter({ hasText: name });
}

test("the buyer confirms each parcel arrived, the makers are told, and the order completes", async ({
  page,
  request,
}) => {
  const orderId = await freshOrder(request);
  await approveAtSimulatedPayPal(page, orderId);

  for (const name of ["Priya", "Lucía", "Grace"]) {
    await row(page, name).getByRole("button", { name: /Simulate proof of shipping/ }).click();
    await expect(row(page, name)).toContainText("Paid on proof of shipping");
  }
  // Only a parcel that shipped can be received: Amina's share is still reserved, with nothing to confirm.
  await expect(row(page, "Amina").getByRole("button", { name: /Confirm delivery/ })).toHaveCount(0);
  // Amina does not ship: her share goes back to the buyer.
  expect((await request.post(`${E2E_API_URL}/api/dev/release-reserved-shares`)).ok()).toBeTruthy();
  await page.reload();
  await expect(row(page, "Amina")).toContainText("Released back to you");

  for (const name of ["Priya", "Lucía"]) {
    await row(page, name).getByRole("button", { name: `Confirm delivery of ${name}'s parcel` }).click();
    await expect(row(page, name)).toContainText("Delivered to you");
    await expect(row(page, name)).toContainText(/Received [A-Z][a-z]+ \d{1,2}, \d{4}, on time/);
  }
  await expect(page.getByRole("heading", { level: 1, name: "Order complete" })).toHaveCount(0);
  await row(page, "Grace").getByRole("button", { name: "Confirm delivery of Grace's parcel" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Order complete" })).toBeVisible();
  await expect(page.getByText("Every parcel that shipped has arrived, and every maker who shipped is paid.")).toBeVisible();
  await expect(page.getByRole("button", { name: /Confirm delivery/ })).toHaveCount(0);
  await page.screenshot({ path: path.join(SCREENSHOTS, "order-complete.png"), fullPage: true });

  // The buyer's agent sees the same.
  await connect(request);
  const status = await getOrderStatus(request, orderId);
  expect(status.status).toBe("completed");
  const shares = status.shares as { seller_name: string; status: string; on_time: boolean | null }[];
  expect(shares.find((share) => share.seller_name === "Priya")).toMatchObject({ status: "delivered", on_time: true });
  expect(shares.find((share) => share.seller_name === "Amina")).toMatchObject({ status: "released", on_time: null });

  // Priya is told in Hindi, in her chat.
  await page.goto("/seller-chat?seller=s_priya");
  await expect(page.getByRole("list", { name: "Messages with Priya" })).toContainText(
    `खुशखबरी, Priya! खरीदार को ऑर्डर ${orderId} का आपका पार्सल`,
  );

  await page.goto("/demo");
  const feed = page.getByRole("list", { name: "Activity, newest first" });
  await expect(feed.getByText(`The buyer received Grace's parcel for order ${orderId}`, { exact: false })).toBeVisible();
  await expect(feed.getByText(`Order ${orderId} is complete: 3 makers delivered 28 units`, { exact: false })).toBeVisible();
  await expect(
    feed.getByText(/Priya's trust passport was signed again after her delivery: \d+ orders delivered/).first(),
  ).toBeVisible();

  // Her stall and her trust card say the delivery counted, and that the rest of her record is seeded.
  const card = await getTrustCard(request, "s_priya");
  expect(card.live_deliveries as number).toBeGreaterThanOrEqual(1);
  expect(card.data_source).toBe("seeded_demo");
  await page.goto("/stall/s_priya");
  const trust = page.getByRole("region", { name: "Priya's trust record" });
  await expect(trust).toContainText(`${card.orders_delivered} orders delivered`);
  await expect(trust).toContainText(/\d+ of these orders came through OpenStall, and her record was signed again on/);
  await expect(trust).toContainText("The rest are seeded demo numbers, not real sales.");
});
