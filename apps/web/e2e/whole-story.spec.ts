import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// The whole story, end to end, twice (prompt 47, spec section 2 and section 7's "Full demo runs twice in a row from a
// fresh seed"). Each run starts from a fresh seed and plays all thirteen steps in test mode through the pages a person
// uses: a new seller's photo and Urdu voice note become a live listing; the buyer agent's request is quoted by the
// makers' agents, checked and split; one approval reserves the money; each maker is told on her phone, in her
// language; Amina proves she shipped with her courier receipt and is paid, her tracking on the PayPal order; the buyer
// receives her parcel and her trust passport is signed again, and its signature checks; and the dashboard shows Demand
// Radar's tip. The second run must tell the same story as the first.
const SCREENSHOTS = path.join(__dirname, "screenshots");

// The demo world is put back as seeded afterwards: this spec publishes a listing and signs passports again.
test.afterAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  expect((await api.post(`${E2E_API_URL}/api/demo/reset`)).ok()).toBeTruthy();
  await api.dispose();
});

const URDU = {
  days: "آپ کا پارسل امریکہ میں خریدار تک کتنے دن میں پہنچتا ہے؟",
  city: "پارسل کس شہر سے بھیجا جائے گا؟",
  lowest: "بڑے آرڈر میں ایک عدد کی کم سے کم قیمت کتنی ہو سکتی ہے، امریکی ڈالر میں؟",
  leadDays: "آرڈر تیار کرنے کے لیے آپ کو کم سے کم کتنے دن چاہئیں؟",
  confirm: 'اشتہار لگانے کے لیے "ہاں" لکھیں، یا بتائیں کہ کیا بدلنا ہے۔',
  live: "آپ کا اشتہار لگ گیا ہے!",
};

type Story = { orderId: string; total: string; split: string; aminaPaid: string; told: string };

function controls(page: Page) {
  return page.getByRole("region", { name: "Run the story" });
}

function payments(page: Page) {
  return page.getByRole("region", { name: "Payments" });
}

function phone(page: Page, name: string) {
  return page.getByRole("article", { name: `${name}'s phone` });
}

function receiptRow(page: Page, name: string) {
  return page.getByRole("list", { name: "Each maker's share" }).getByRole("listitem").filter({ hasText: name });
}

async function playTheStory(page: Page, run: number): Promise<Story> {
  // A fresh seed: the five makers as seeded, no orders open.
  expect((await page.request.post(`${E2E_API_URL}/api/demo/reset`)).ok()).toBeTruthy();

  // 1 and 2. A new seller sends a photo and an Urdu voice note; one question at a time; her yes publishes it.
  await page.goto("/seller-chat");
  const composer = page.getByRole("form", { name: "Send a message" });
  const thread = page.getByRole("list", { name: "Your messages with OpenStall" });
  await composer.getByRole("button", { name: "Attach the sample photo" }).click();
  await composer.getByRole("button", { name: "Attach the sample voice note" }).click();
  await composer.getByRole("button", { name: "Send" }).click();
  await expect(thread).toContainText(URDU.days);
  for (const [words, next] of [
    ["9", URDU.city],
    ["Lahore", URDU.lowest],
    ["15", URDU.leadDays],
    ["5", URDU.confirm],
    ["ہاں", URDU.live],
  ]) {
    await composer.getByLabel("Message").fill(words);
    await composer.getByRole("button", { name: "Send" }).click();
    await expect(thread).toContainText(next);
  }
  await expect(page.getByRole("region", { name: /Your listing is live/ })).toContainText("Hand-embroidered cushion cover");

  // 3 to 7. The seeded makers are live; the buyer agent's request is quoted by their agents, checked, and split.
  await page.goto("/demo");
  await expect(page.getByRole("status").filter({ hasText: /^Live$/ })).toBeVisible();
  await controls(page).getByRole("button", { name: "Run the demo request" }).click();
  await expect(controls(page).getByRole("status")).toContainText("drafted: $");
  const status = (await controls(page).getByRole("status").textContent()) ?? "";
  const orderId = (await controls(page).getByRole("status").locator(".font-mono").textContent())?.trim() ?? "";
  expect(orderId).toMatch(/^ord_/);
  const total = status.match(/drafted: (\$[\d,]+\.\d\d)/)?.[1] ?? "";
  expect(total).not.toBe("");
  const allocation = page.getByRole("region", { name: "Allocation", exact: true });
  // The panel follows the live feed and may still show the seeded plan for a moment: wait for this request's plan,
  // whose total is the order's.
  await expect(allocation).toContainText(`makers, ${total}`);
  const split = ((await allocation.textContent()) ?? "").match(/All 40 from \d+ makers, \$[\d,]+\.\d\d/)?.[0] ?? "";
  await expect(page.getByRole("region", { name: "Offers", exact: true })).toContainText("Valid");

  // 8 and 9. The person sees the makers, quantities, total and dates, and approves one PayPal checkout.
  await controls(page).getByRole("link", { name: "Open its approval page" }).click();
  await expect(page.getByText(`One PayPal authorization for ${total}.`, { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Approve and pay with PayPal" }).click();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: `Simulated PayPal is holding ${total}` })).toBeVisible();
  const receipt = page.url();

  // 10. Each maker's phone has her order, in her language.
  await page.goto("/demo");
  await expect(page.getByRole("status").filter({ hasText: /^Live$/ })).toBeVisible();
  // The new seller's listing joined the quote, so the split decides who is in the order: every maker in it has her
  // phone here, and each has the order. Amina's is in Urdu.
  const phones = page.getByRole("article", { name: /'s phone$/ });
  await expect(phones.first()).toBeVisible();
  for (const each of await phones.all()) await expect(each).toContainText(orderId);
  await expect(phone(page, "Amina")).toContainText(`آرڈر: ${orderId}`);
  const told = (await phones.count()).toString();

  // 11. Amina sends her courier receipt; the tracking number is read, she confirms it, she is paid, and her tracking
  // goes on the PayPal order.
  await phone(page, "Amina").getByRole("button", { name: /Send Amina's courier receipt/ }).click();
  await expect(phone(page, "Amina")).toContainText("ٹریکنگ نمبر: 7712345678");
  await phone(page, "Amina").getByRole("button", { name: /Reply\s*“\s*ہاں\s*”\s*as Amina/ }).click();
  await expect(phone(page, "Amina")).toContainText("آپ کو ادائیگی ہو گئی!");
  const amina = payments(page).getByRole("list", { name: "Each maker's payment" }).getByRole("listitem").filter({ hasText: "Amina" });
  await expect(amina).toContainText("Paid on proof of shipping");
  await expect(amina).toContainText("Tracking on the simulated PayPal order");
  // Her row's money, in order: her units' price, her share, what she was paid.
  const aminaPaid = (((await amina.textContent()) ?? "").match(/\$[\d,]+\.\d\d/g) ?? []).join(" ");
  expect(aminaPaid).not.toBe("");

  // 12. The buyer receives her parcel; her trust passport is signed again, and its signature holds.
  await page.goto(receipt);
  await receiptRow(page, "Amina").getByRole("button", { name: "Confirm delivery of Amina's parcel" }).click();
  await expect(receiptRow(page, "Amina")).toContainText("Delivered to you");
  const verified = await page.request.get(`${E2E_API_URL}/passport/s_amina/verify`);
  expect(verified.ok()).toBeTruthy();
  expect(((await verified.json()) as { valid: boolean }).valid).toBe(true);
  await page.goto("/demo");
  await expect(page.getByRole("list", { name: "Activity, newest first" })).toContainText(
    "Amina's trust passport was signed again after her delivery",
  );

  // 13. The dashboard shows Demand Radar's tip.
  await page.goto("/dashboard");
  await expect(page.getByText("23 agents searched for ceramic mugs this week. Nobody sells them.").first()).toBeVisible();
  await page.screenshot({ path: path.join(SCREENSHOTS, `whole-story-run-${run}.png`), fullPage: false });

  return { orderId, total, split, aminaPaid, told };
}

test("the whole story runs twice in a row from a fresh seed, and tells the same story both times", async ({ page }) => {
  test.setTimeout(240_000);
  await page.setViewportSize({ width: 1280, height: 900 });

  const first = await playTheStory(page, 1);
  const second = await playTheStory(page, 2);

  expect(second.orderId).not.toBe(first.orderId); // a new order each time
  expect({ ...second, orderId: "" }).toEqual({ ...first, orderId: "" });
});
