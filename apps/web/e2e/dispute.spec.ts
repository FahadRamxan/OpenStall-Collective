import path from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// Disputes answered with the proof (prompt 56), in fake mode: Priya is paid on proof, then the buyer opens a PayPal
// dispute saying her parcel never came. OpenStall answers it with her proof of shipping, simulated PayPal decides in her
// favour, and she is told in Hindi. No money moves on OpenStall's side.
const SCREENSHOTS = path.join(__dirname, "screenshots");

async function freshOrder(request: APIRequestContext): Promise<string> {
  // Earlier spec files leave story orders reserved; release them, so this order is each maker's only open share.
  expect((await request.post(`${E2E_API_URL}/api/dev/release-reserved-shares`)).status()).toBe(200);
  const response = await request.post(`${E2E_API_URL}/api/dev/story-orders`);
  expect(response.status()).toBe(201);
  return ((await response.json()) as { order_id: string }).order_id;
}

async function approveAtSimulatedPayPal(page: Page, orderId: string) {
  await page.goto(`/approve/${orderId}`);
  await page.getByRole("button", { name: "Approve and pay with PayPal" }).click();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Simulated PayPal is holding $815.00" })).toBeVisible();
}

function row(page: Page, name: string) {
  return page.getByRole("list", { name: "Each maker's share" }).getByRole("listitem").filter({ hasText: name });
}

test("a buyer's dispute on Priya's parcel is answered with her proof, and decided in her favour", async ({
  page,
  request,
}) => {
  const orderId = await freshOrder(request);
  await approveAtSimulatedPayPal(page, orderId);

  // Only a paid share can be disputed: no dispute button before she ships.
  await expect(row(page, "Priya").getByRole("button", { name: /Dispute this parcel/ })).toHaveCount(0);
  await row(page, "Priya").getByRole("button", { name: /Simulate proof of shipping/ }).click();
  await expect(row(page, "Priya")).toContainText("Paid on proof of shipping");

  const dispute = row(page, "Priya").getByRole("button", { name: /Dispute this parcel at PayPal/ });
  await expect(dispute).toContainText("Simulated");
  await dispute.click();

  await expect(row(page, "Priya")).toContainText(
    "PayPal dispute (the parcel did not arrive): decided in her favour (simulated PayPal)",
  );
  await expect(row(page, "Priya").getByRole("button", { name: /Dispute this parcel/ })).toHaveCount(0);
  await expect(row(page, "Priya")).toContainText("Paid on proof of shipping"); // her payment stands
  await page.screenshot({ path: path.join(SCREENSHOTS, "dispute-receipt-1280.png"), fullPage: true });

  // The live feed tells it in order.
  await page.goto("/demo");
  const feed = page.getByRole("list", { name: "Activity, newest first" });
  await expect(feed).toContainText(
    `The buyer opened a PayPal dispute on Priya's share of order ${orderId} ($176.00): the parcel did not arrive.`,
  );
  await expect(feed).toContainText(
    `OpenStall answered the buyer's PayPal dispute on Priya's share of order ${orderId} with her proof of shipping`,
  );
  await expect(feed).toContainText(
    `PayPal decided the buyer's dispute on Priya's share of order ${orderId}: in her favour (simulated PayPal)`,
  );

  // Priya is told in Hindi that PayPal has her proof, and then that the dispute closed in her favour.
  await page.goto("/seller-chat?seller=s_priya");
  const chat = page.getByRole("list", { name: "Messages with Priya" });
  await expect(chat).toContainText(`एक खरीदार ने ऑर्डर ${orderId} पर PayPal में शिकायत की है कि पार्सल नहीं पहुँचा।`);
  await expect(chat).toContainText(`PayPal ने ऑर्डर ${orderId} की शिकायत आपके पक्ष में बंद कर दी है।`);
});
