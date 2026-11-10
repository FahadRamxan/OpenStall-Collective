import { expect, test } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// A listing from a chat (prompts 17 to 19, spec 3.1 steps 3 to 6): what a new seller sends is read into a draft
// listing shown under her chat; each answer asks her one short question, in her language, for what is still missing,
// then for her limits; once nothing is missing she gets all of it back, and her yes publishes it. Test mode reads its
// sample photo as the seeded Amina's cushion cover, and its sample voice note as her words in Urdu: 18 dollars each,
// four a week. Her bare answers ("9") answer the question asked.
const ASK = {
  days: "آپ کا پارسل امریکہ میں خریدار تک کتنے دن میں پہنچتا ہے؟",
  city: "پارسل کس شہر سے بھیجا جائے گا؟",
  lowest: "بڑے آرڈر میں ایک عدد کی کم سے کم قیمت کتنی ہو سکتی ہے، امریکی ڈالر میں؟",
  leadDays: "آرڈر تیار کرنے کے لیے آپ کو کم سے کم کتنے دن چاہئیں؟",
  // Her item is named in Urdu in messages to her; the listing itself keeps its English title for buyers.
  summary: "یہ رہا آپ کا اشتہار: ہاتھ کی کڑھائی والا کشن کور",
  confirm: 'اشتہار لگانے کے لیے "ہاں" لکھیں، یا بتائیں کہ کیا بدلنا ہے۔',
  live: "آپ کا اشتہار لگ گیا ہے!",
};

// The first test publishes a cushion cover. Put the demo world back as seeded afterwards: later spec files search and
// quote the story's request, and expect its five makers only.
test.afterAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  expect((await api.post(`${E2E_API_URL}/api/demo/reset`)).ok()).toBeTruthy();
  await api.dispose();
});

test("the sample photo and voice note become a listing: one question at a time in Urdu, then her yes", async ({
  page,
}) => {
  await page.goto("/seller-chat");
  const composer = page.getByRole("form", { name: "Send a message" });
  const thread = page.getByRole("list", { name: "Your messages with OpenStall" });

  await composer.getByRole("button", { name: "Attach the sample photo" }).click();
  await expect(composer.getByRole("button", { name: "Remove sample-photo.png" })).toBeVisible();
  await composer.getByRole("button", { name: "Attach the sample voice note" }).click();
  await expect(composer.getByRole("button", { name: "Remove the voice note" })).toBeVisible();
  await composer.getByRole("button", { name: "Send" }).click();

  const draft = page.getByRole("region", { name: /Your listing so far/ });
  await expect(draft).toContainText("Hand-embroidered cushion cover");
  await expect(draft).toContainText("$18.00 each");
  await expect(draft).toContainText("In your words: اٹھارہ ڈالر");
  await expect(draft).toContainText("4 a week");
  await expect(draft.getByText("Asking now")).toHaveCount(1);
  await expect(draft.getByText("Still to ask")).toHaveCount(3);
  await expect(draft.getByRole("img", { name: "A listing photo" })).toHaveCount(1);
  await expect(thread).toContainText(ASK.days);

  async function answer(words: string, next: string) {
    await composer.getByLabel("Message").fill(words);
    await composer.getByRole("button", { name: "Send" }).click();
    await expect(thread).toContainText(next);
  }

  await answer("9", ASK.city);
  await expect(draft).toContainText("9 days to arrive");
  await answer("Lahore", ASK.lowest);
  await expect(draft).toContainText("Lahore");
  await answer("15", ASK.leadDays);
  await expect(draft).toContainText("$15.00 each, for a big order");
  await answer("5", ASK.confirm);
  await expect(thread).toContainText(ASK.summary);
  await expect(draft).toContainText("5 days at least");
  await expect(draft.getByText("Still to ask")).toHaveCount(0);
  await expect(draft.getByText("Asking now")).toHaveCount(0);
  await expect(draft).toContainText("Waiting for your yes");
  await expect(draft.getByRole("heading", { name: "Your limits" })).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/listing-draft.png", fullPage: true });

  await answer("ہاں", ASK.live);
  const live = page.getByRole("region", { name: /Your listing is live/ });
  await expect(live).toContainText("Hand-embroidered cushion cover, $18.00 each.");
  await expect(page.getByRole("region", { name: /Your listing so far/ })).toHaveCount(0);
  await page.screenshot({ path: "e2e/screenshots/listing-live.png", fullPage: true });

  await live.getByRole("link", { name: "Open your stall" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Web seller");
  await expect(page.getByText("Hand-embroidered cushion cover").first()).toBeVisible();

  await page.goto("/demo");
  const feed = page.getByRole("list", { name: "Activity, newest first" });
  await expect(
    feed.getByText(/listing draft has everything it needs: Hand-embroidered cushion cover.*5 days to make an order/).first(),
  ).toBeVisible();
  await expect(feed.getByText(/listing is live: Hand-embroidered cushion cover/).first()).toBeVisible();
});

test("typed in English, she is asked in English, a photo first", async ({ page }) => {
  await page.goto("/seller-chat");
  const composer = page.getByRole("form", { name: "Send a message" });
  const thread = page.getByRole("list", { name: "Your messages with OpenStall" });

  await composer.getByLabel("Message").fill("I make quilts, $45 each, 3 a week.");
  await composer.getByRole("button", { name: "Send" }).click();

  await expect(thread).toContainText("Your listing so far: your item, not named yet, $45.00 each, 3 a week.");
  await expect(thread).toContainText("Please send a photo of it.");
  await expect(page.getByRole("region", { name: /Your listing so far/ }).getByText("Asking now")).toHaveCount(1);
});

test("a hello alone starts no draft listing", async ({ page }) => {
  await page.goto("/seller-chat");
  const composer = page.getByRole("form", { name: "Send a message" });

  await composer.getByLabel("Message").fill("Hello");
  await composer.getByRole("button", { name: "Send" }).click();

  await expect(page.getByRole("list", { name: "Your messages with OpenStall" })).toContainText("Welcome to OpenStall!");
  await expect(page.getByRole("region", { name: /Your listing so far/ })).toHaveCount(0);
});
