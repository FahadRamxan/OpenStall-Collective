import path from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// Snap the receipt, get paid (prompt 32): once PayPal holds the order, a maker photographs her courier receipt; the
// model reads the courier and tracking number (fake mode's stand-in reads fake mode's own receipt photo); she
// confirms it in her language, and only then is her share captured and paid, and she is told. The seeded makers have
// no phone, so this page plays them in test mode.
const SCREENSHOTS = path.join(__dirname, "screenshots");

// One tracking number pays one share (proof.py). An earlier spec file paid Priya with fake mode's sample receipt,
// whose usual number this one checks for, so the demo world is put back as seeded first and that number is free.
test.beforeAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  expect((await api.post(`${E2E_API_URL}/api/demo/reset`)).ok()).toBeTruthy();
  await api.dispose();
});

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
  await expect(page.getByText("Each maker has been told about her share, in her own language.")).toBeVisible();
}

function row(page: Page, name: string) {
  return page.getByRole("list", { name: "Each maker's share" }).getByRole("listitem").filter({ hasText: name });
}

test("Priya photographs her courier receipt, confirms it in Hindi, and is paid on proof", async ({ page, request }) => {
  const orderId = await freshOrder(request);
  await approveAtSimulatedPayPal(page, orderId);

  // Her chat, played in test mode: the receipt photo, read and asked about in Hindi.
  await page.goto("/seller-chat?seller=s_priya");
  const panel = page.getByRole("region", { name: /Play Priya/ });
  await expect(panel).toContainText("Test mode");
  await panel.getByRole("button", { name: /Send her courier receipt photo/ }).click();
  const thread = page.getByRole("list", { name: "Messages with Priya" });
  await expect(thread).toContainText(`मैंने ऑर्डर ${orderId} (11 × Mirror-work embroidered cushion cover) की कूरियर रसीद`);
  await expect(thread).toContainText("कूरियर: India Post");
  await expect(thread).toContainText("ट्रैकिंग नंबर: EE123456789IN");
  const receipt = thread.getByRole("img", { name: "A photo the seller sent" }).last();
  await expect(receipt).toBeVisible();
  await expect.poll(() => receipt.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);

  // Nothing is paid on the reading alone: the receipt says what was read, waiting for her.
  const order = (await (await request.get(`${E2E_API_URL}/api/orders/${orderId}`)).json()) as {
    parts: { seller: { name: string }; status: string; tracking_number: string | null }[];
  };
  const before = order.parts.find((part) => part.seller.name === "Priya");
  expect(before).toMatchObject({ status: "authorized", tracking_number: null });

  // She confirms, and is paid.
  await panel.getByRole("textbox", { name: "Reply as Priya" }).fill("हाँ");
  await panel.getByRole("button", { name: "Send as Priya" }).click();
  await expect(thread).toContainText("आपका ट्रैकिंग नंबर EE123456789IN सेव हो गया है");
  await expect(thread).toContainText(`आपको भुगतान हो गया! ऑर्डर ${orderId} के $176.00 आपके PayPal खाते में भेज दिए गए हैं।`);
  await expect(thread).toContainText("(टेस्ट मोड: नकली PayPal, कोई असली पैसा नहीं भेजा गया।)");
  await page.screenshot({ path: path.join(SCREENSHOTS, "receipt-chat-priya-1280.png"), fullPage: true });

  // The buyer's receipt: Priya paid on proof, her tracking and her courier receipt.
  await page.goto(`/approve/${orderId}/return`);
  await expect(row(page, "Priya")).toContainText("Paid on proof of shipping");
  await expect(row(page, "Priya")).toContainText("Shipped with India Post: EE123456789IN");
  await expect(row(page, "Priya").getByRole("link", { name: "See her courier receipt" })).toBeVisible();
  // Prompt 33: her tracking is on her payment at (simulated) PayPal.
  await expect(row(page, "Priya")).toContainText("Tracking on the simulated PayPal order");
  await expect(row(page, "Lucía")).toContainText("Reserved, paid when she ships");
  await page.screenshot({ path: path.join(SCREENSHOTS, "receipt-paid-1280.png"), fullPage: true });

  // The live feed tells it in order.
  await page.goto("/demo");
  const feed = page.getByRole("list", { name: "Activity, newest first" });
  await expect(feed).toContainText(`Priya confirmed her tracking for order ${orderId}: India Post EE123456789IN`);
  await expect(feed).toContainText("Priya was paid $176.00 on proof of shipping");
  await expect(feed).toContainText("Priya's tracking (India Post EE123456789IN) is on simulated PayPal order");
  await expect(feed).toContainText(`Priya was told in the web chat, in Hindi, that she is paid for order ${orderId}`);
});

test("Amina confirms her receipt in Urdu, and is paid to her bank through Hyperwallet (simulated)", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const orderId = await freshOrder(request);
  await approveAtSimulatedPayPal(page, orderId);

  await page.goto("/seller-chat?seller=s_amina");
  const panel = page.getByRole("region", { name: /Play Amina/ });
  await panel.getByRole("button", { name: /Send her courier receipt photo/ }).click();
  const thread = page.getByRole("list", { name: "Messages with Amina" });
  await expect(thread).toContainText("ٹریکنگ نمبر: 7712345678");
  await panel.getByRole("textbox", { name: "Reply as Amina" }).fill("جی ہاں");
  await panel.getByRole("button", { name: "Send as Amina" }).click();

  await expect(thread).toContainText("آپ کا ٹریکنگ نمبر 7712345678 محفوظ ہو گیا ہے");
  await expect(thread).toContainText("216.00 ڈالر ابھی ادا کیے جا رہے ہیں");
  await expect(thread).toContainText("Hyperwallet کے ذریعے آپ کے بینک اکاؤنٹ میں بھیج دیے گئے ہیں");
  await expect(thread).toContainText("(ٹیسٹ موڈ: نقلی PayPal، کوئی اصل رقم منتقل نہیں ہوئی۔)");
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: path.join(SCREENSHOTS, "receipt-chat-amina-375.png"), fullPage: true });

  // Her share is captured like anyone's, so her tracking goes on the PayPal order; her bank payout through
  // Hyperwallet is simulated (prompt 52).
  await page.goto(`/approve/${orderId}/return`);
  await expect(row(page, "Amina")).toContainText("Shipped with TCS: 7712345678");
  await expect(row(page, "Amina")).toContainText("Paid on proof of shipping");
  await expect(row(page, "Amina")).toContainText("Paid to her bank through Hyperwallet (simulated)");
  await expect(row(page, "Amina")).toContainText("Tracking on the simulated PayPal order");
});
