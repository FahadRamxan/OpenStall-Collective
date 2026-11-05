import path from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// Telling each maker about her share (prompt 31): once the buyer approves and PayPal holds the order, each maker gets
// one message in her language (Urdu, Hindi, Spanish, English), in the web chat here, since the seeded makers have no
// WhatsApp number. The receipt says who was told, her chat shows the message, and the live feed records it.
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

function row(page: Page, name: string) {
  return page.getByRole("list", { name: "Each maker's share" }).getByRole("listitem").filter({ hasText: name });
}

type Part = { seller: { name: string }; ship_by: string | null };

test("once PayPal holds the order, each maker is told about her share in her language, and her chat shows it", async ({
  page,
  request,
}) => {
  const orderId = await freshOrder(request);
  await approveAtSimulatedPayPal(page, orderId);

  // The receipt: every maker told, where and in which language.
  await expect(page.getByText("Each maker has been told about her share, in her own language.")).toBeVisible();
  await expect(row(page, "Amina")).toContainText("Told in the web chat, in Urdu");
  await expect(row(page, "Priya")).toContainText("Told in the web chat, in Hindi");
  await expect(row(page, "Lucía")).toContainText("Told in the web chat, in Spanish");
  await expect(row(page, "Grace")).toContainText("Told in the web chat, in English");
  // When each share must leave her, as the API worked it out: the delivery date less her ship days.
  const order = (await (await request.get(`${E2E_API_URL}/api/orders/${orderId}`)).json()) as { parts: Part[] };
  for (const part of order.parts) {
    expect(part.ship_by).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    await expect(row(page, part.seller.name)).toContainText(/ships by \w+ \d{1,2}, \d{4}, arrives by \w+ \d{1,2}, \d{4}/);
  }
  await page.screenshot({ path: path.join(SCREENSHOTS, "notify-receipt-1280.png"), fullPage: true });

  // Priya's chat, from her row: the message in Hindi, with this order and her 11 covers.
  await row(page, "Priya").getByRole("link", { name: "See Priya's chat" }).click();
  await expect(page).toHaveURL(/\/seller-chat\?seller=s_priya$/);
  const priya = page.getByRole("list", { name: "Messages with Priya" });
  await expect(priya).toContainText("नमस्ते Priya! OpenStall से आपके लिए एक नया ऑर्डर आया है।");
  await expect(priya).toContainText(`ऑर्डर: ${orderId}`);
  await expect(priya).toContainText("संख्या: 11");
  await expect(priya).toContainText("पहुँचाना है: Chicago");
  await expect(priya).toContainText("रसीद की फ़ोटो यहाँ भेजें"); // send the courier receipt photo here to be paid
  await expect(page.getByRole("list", { name: "Sellers who have chatted" }).getByRole("link", { name: /Priya/ })).toHaveAttribute(
    "aria-current",
    "page",
  );

  // Amina's, in Urdu: no payout rail reaches Pakistan yet, so she is asked to wait for us before she ships.
  await page.goto("/seller-chat?seller=s_amina");
  const amina = page.getByRole("list", { name: "Messages with Amina" });
  await expect(amina).toContainText("السلام علیکم Amina!");
  await expect(amina).toContainText(`آرڈر: ${orderId}`);
  await expect(amina).toContainText("قیمت: 18.00 ڈالر فی عدد، کل 216.00 ڈالر"); // dollars as Urdu writes them
  await expect(amina).toContainText("ادائیگی کا انتظام ابھی مکمل نہیں ہوا");
  await page.screenshot({ path: path.join(SCREENSHOTS, "notify-chat-amina-1280.png"), fullPage: true });

  // Lucía's, in Spanish, in US dollars.
  await page.goto("/seller-chat?seller=s_lucia");
  const lucia = page.getByRole("list", { name: "Messages with Lucía" });
  await expect(lucia).toContainText("¡Hola, Lucía! Tienes un pedido nuevo de OpenStall.");
  await expect(lucia).toContainText("Precio: US$22.00 cada uno, US$220.00 en total");

  // The live demo: the order card counts the makers told, and the feed says each was told, in the web chat.
  await page.goto("/demo");
  await expect(page.getByText("Makers told: 4 of 4")).toBeVisible();
  const feed = page.getByRole("list", { name: "Activity, newest first" });
  await expect(feed).toContainText("Grace was told about her share in the web chat, in English: 7 to ship by");
  await expect(feed.getByRole("listitem").filter({ hasText: "Grace was told about her share" }).first()).toContainText(
    "Web chat",
  );
});

test("the receipt with each maker told fits a phone screen", async ({ page, request }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const orderId = await freshOrder(request);
  await approveAtSimulatedPayPal(page, orderId);

  await expect(page.getByText("Each maker has been told about her share, in her own language.")).toBeVisible();
  await expect(row(page, "Lucía").getByRole("link", { name: "See Lucía's chat" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: path.join(SCREENSHOTS, "notify-receipt-375.png"), fullPage: true });

  // Reserving again (a reload) tells nobody twice: each maker has exactly one message about this order.
  await page.reload();
  await expect(page.getByText("Each maker has been told about her share, in her own language.")).toBeVisible();
  for (const seller of ["s_amina", "s_priya", "s_lucia", "s_grace"]) {
    const chat = (await (await request.get(`${E2E_API_URL}/api/chats/${seller}`)).json()) as {
      messages: { text: string | null }[];
    };
    expect(chat.messages.filter((message) => message.text?.includes(orderId))).toHaveLength(1);
  }
});
