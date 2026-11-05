import { expect, test } from "@playwright/test";

// A draft listing from photos and words (prompt 17, spec 3.1 step 3): what a new seller sends is read into a draft
// listing, told back to her with what it still needs, and shown under her chat. Test mode reads its sample photo as
// the seeded Amina's cushion cover, and its sample voice note as her words in Urdu: 18 dollars each, four a week.
test("the sample photo and voice note become a draft listing, and what she types next fills the rest", async ({
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
  await expect(draft.getByText("Still to ask")).toHaveCount(2);
  await expect(draft.getByRole("img", { name: "A listing photo" })).toHaveCount(1);
  await expect(thread).toContainText("Still needed: how many days delivery takes and the city it ships from.");

  await composer.getByLabel("Message").fill("Delivery takes 9 days. It ships from Lahore.");
  await composer.getByRole("button", { name: "Send" }).click();

  await expect(draft).toContainText("9 days to arrive");
  await expect(draft).toContainText("Lahore");
  await expect(draft.getByText("Still to ask")).toHaveCount(0);
  await expect(thread).toContainText("That is everything it needs.");
  await page.screenshot({ path: "e2e/screenshots/listing-draft.png", fullPage: true });

  await page.goto("/demo");
  const feed = page.getByRole("list", { name: "Activity, newest first" });
  await expect(feed.getByText(/listing draft has everything it needs: Hand-embroidered cushion cover/).first()).toBeVisible();
});

test("a hello alone starts no draft listing", async ({ page }) => {
  await page.goto("/seller-chat");
  const composer = page.getByRole("form", { name: "Send a message" });

  await composer.getByLabel("Message").fill("Hello");
  await composer.getByRole("button", { name: "Send" }).click();

  await expect(page.getByRole("list", { name: "Your messages with OpenStall" })).toContainText("Welcome to OpenStall!");
  await expect(page.getByRole("region", { name: /Your listing so far/ })).toHaveCount(0);
});
