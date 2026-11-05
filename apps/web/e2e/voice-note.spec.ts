import { expect, test } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// Voice notes to text (prompt 16, spec 3.1 step 2): a seller's voice note becomes text before her message is stored,
// kept word for word as she said it, and its language goes on her profile. Test mode hears its sample voice note as
// Amina's words from the story, in Urdu: "Embroidered cushion covers, in three colours, 18 dollars each. I can make
// 15 a week."
const URDU = "کڑھائی والے کشن کور، تین رنگوں میں، اٹھارہ ڈالر کا ایک۔ میں ہفتے میں پندرہ بنا سکتی ہوں۔";

test("in the web chat, the sample voice note comes back as her words in Urdu, and the live feed says so", async ({
  page,
}) => {
  await page.goto("/seller-chat");
  const composer = page.getByRole("form", { name: "Send a message" });

  await composer.getByRole("button", { name: /Attach the sample voice note/ }).click();
  await expect(composer.getByRole("button", { name: "Remove the voice note" })).toBeVisible();
  await composer.getByRole("button", { name: "Send" }).click();

  const thread = page.getByRole("list", { name: "Your messages with OpenStall" });
  const words = thread.getByText(URDU);
  await expect(words).toBeVisible();
  await expect(words).toHaveAttribute("lang", "ur");
  await expect(thread.getByText("Voice note in Urdu, as text")).toBeVisible();
  await expect(thread.locator("audio")).toHaveCount(1);
  await page.screenshot({ path: "e2e/screenshots/voice-note-web-chat.png", fullPage: true });

  await page.goto("/demo");
  const feed = page.getByRole("list", { name: "Activity, newest first" });
  await expect(
    feed.getByText(/voice note was turned into text, in Urdu, now saved as her language/).first(),
  ).toBeVisible();
});

test("a voice note that arrives on WhatsApp shows as text in her chat", async ({ page, request }) => {
  const number = `+9230055${String(Date.now()).slice(-5)}`;
  const sent = await request.post(`${E2E_API_URL}/api/dev/inbound`, {
    data: { sender: number, profile_name: "Rukhsana", voice_note: true },
  });
  expect(sent.status()).toBe(201);
  const { seller_id: sellerId } = (await sent.json()) as { seller_id: string };

  await page.goto(`/seller-chat?seller=${encodeURIComponent(sellerId)}`);

  const thread = page.getByRole("list", { name: "Messages with Rukhsana" });
  await expect(thread.getByText(URDU)).toBeVisible();
  await expect(thread.getByText("Voice note in Urdu, as text")).toBeVisible();
});
