import path from "node:path";

import { expect, test, type APIRequestContext } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

const SCREENSHOTS = path.join(__dirname, "screenshots");

/** As if a seller sent this on WhatsApp (fake mode's /api/dev/inbound takes the webhook's own path). */
async function sendOnWhatsApp(request: APIRequestContext, data: Record<string, unknown>): Promise<string> {
  const response = await request.post(`${E2E_API_URL}/api/dev/inbound`, { data });
  expect(response.status()).toBe(201);
  return ((await response.json()) as { seller_id: string }).seller_id;
}

test("a WhatsApp message with a photo shows in the seller's chat, and her next one arrives live", async ({
  page,
  request,
}) => {
  const sender = `+92300${String(Date.now()).slice(-7)}`;
  const sellerId = await sendOnWhatsApp(request, {
    sender,
    profile_name: "Shazia",
    text: "Salaam! These are my cushion covers.",
    photo: true,
  });

  await page.goto(`/seller-chat?seller=${sellerId}`);

  const thread = page.getByRole("list", { name: "Messages with Shazia" });
  await expect(thread).toContainText("Salaam! These are my cushion covers.");
  const photo = thread.getByRole("img", { name: "A photo the seller sent" });
  await expect(photo).toBeVisible();
  await expect.poll(() => photo.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
  const sellers = page.getByRole("list", { name: "Sellers who have chatted" });
  await expect(sellers.getByRole("link", { name: /Shazia/ })).toHaveAttribute("aria-current", "page");

  await sendOnWhatsApp(request, { sender, profile_name: "Shazia", text: "And here is a voice note.", voice_note: true });

  await expect(thread).toContainText("And here is a voice note.", { timeout: 5_000 });
  await expect(thread.locator("audio")).toHaveCount(1);
  await page.screenshot({ path: path.join(SCREENSHOTS, "seller-chat-1280.png"), fullPage: true });
});

test("the seller chat fits a phone screen", async ({ page, request }) => {
  const sellerId = await sendOnWhatsApp(request, {
    sender: `+92301${String(Date.now()).slice(-7)}`,
    profile_name: "Bushra",
    text: "A long message to check the bubbles wrap on a phone, with no sideways scrolling at all.",
    photo: true,
  });
  await page.setViewportSize({ width: 375, height: 812 });

  await page.goto(`/seller-chat?seller=${sellerId}`);

  await expect(page.getByRole("list", { name: "Messages with Bushra" })).toContainText("no sideways scrolling");
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: path.join(SCREENSHOTS, "seller-chat-375.png"), fullPage: true });
});

test("from your demo phone, a photo and a message get OpenStall's welcome, and you can start over", async ({
  page,
  request,
}) => {
  // A real photo to upload: the made-up embroidery photo, as the API keeps it.
  await sendOnWhatsApp(request, { sender: `+92302${String(Date.now()).slice(-7)}`, text: "photo", photo: true });
  const [chat] = (await (await request.get(`${E2E_API_URL}/api/chats`)).json()) as { seller: { id: string } }[];
  const conversation = await (await request.get(`${E2E_API_URL}/api/chats/${chat.seller.id}`)).json();
  const photo = await (await request.get(`${E2E_API_URL}${conversation.messages[0].media[0].url}`)).body();

  await page.goto("/seller-chat");
  const thread = page.getByRole("list", { name: "Your messages with OpenStall" });
  await expect(thread).toContainText("Send a photo of something you make");

  await page.getByRole("textbox", { name: "Message" }).fill("Salaam! I embroider cushion covers in Lahore.");
  await page.getByLabel("Attach a photo").setInputFiles({ name: "cushion.png", mimeType: "image/png", buffer: photo });
  await expect(page.getByRole("list", { name: "Attached" })).toContainText("cushion.png");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(thread).toContainText("Salaam! I embroider cushion covers in Lahore.");
  await expect(thread).toContainText("Welcome to OpenStall!");
  await expect(thread.getByRole("img", { name: "A photo the seller sent" })).toBeVisible();
  await expect(thread.getByText(/· Sent$/)).toHaveCount(1);

  await page.getByRole("textbox", { name: "Message" }).fill("$18 each, 4 a week.");
  await page.getByRole("textbox", { name: "Message" }).press("Enter");
  await expect(thread).toContainText(
    "Thank you. Your listing so far: Hand-embroidered cushion cover, $18.00 each, 4 a week. How many days does your " +
      "parcel take to reach a buyer in the US?",
  );
  await expect(page.getByRole("list", { name: "Sellers who have chatted" })).toContainText("(you)");
  await page.screenshot({ path: path.join(SCREENSHOTS, "seller-chat-phone-1280.png"), fullPage: true });

  await page.getByRole("button", { name: "Start as a new seller" }).click();

  await expect(thread).toContainText("Send a photo of something you make");
  await expect(thread).not.toContainText("Welcome to OpenStall!");
});
