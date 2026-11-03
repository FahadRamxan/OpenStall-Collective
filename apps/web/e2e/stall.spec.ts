import { expect, test } from "@playwright/test";

// The e2e API is seeded with all five makers (playwright.config.ts runs scripts/seed_demo.py --with-amina).
const STALLS = [
  { id: "s_amina", name: "Amina", price: "$18.00", place: "Lahore, Pakistan", language: "Urdu" },
  { id: "s_priya", name: "Priya", price: "$16.00", place: "Jaipur, India", language: "Hindi" },
  { id: "s_lucia", name: "Lucía", price: "$22.00", place: "Oaxaca, Mexico", language: "Spanish" },
  { id: "s_grace", name: "Grace", price: "$32.00", place: "Detroit, United States", language: "English" },
  { id: "s_noor", name: "Noor", price: "$31.00", place: "Manchester, United Kingdom", language: "Urdu" },
];

for (const stall of STALLS) {
  test(
    `${stall.name}'s stall shows who she is, her listing, a real photo and her trust record`,
    { tag: "@smoke" },
    async ({ page }) => {
      await page.goto(`/stall/${stall.id}`);

      await expect(page.getByRole("heading", { level: 1 })).toHaveText(stall.name);
      await expect(page).toHaveTitle(`${stall.name}'s stall · OpenStall Collective`);
      await expect(page.getByText("Seeded demo seller")).toBeVisible();
      await expect(page.getByText(`${stall.place} · Speaks ${stall.language}`)).toBeVisible();

      const listing = page.getByRole("article");
      await expect(listing.getByText(stall.price, { exact: true })).toBeVisible();
      const photo = listing.getByRole("img", { name: /photo 1/ });
      await expect(photo).toBeVisible();
      await expect.poll(() => photo.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);

      const trust = page.getByRole("region", { name: `${stall.name}'s trust record` });
      await expect(trust).toContainText("orders delivered");
      await expect(trust).toContainText("These are seeded demo numbers, not real sales.");
    },
  );
}

test("the home page lists all five makers, and a card opens its stall", { tag: "@smoke" }, async ({ page }) => {
  await page.goto("/");

  const makers = page.getByRole("region", { name: "Meet the makers" });
  for (const stall of STALLS) {
    await expect(makers.getByRole("link", { name: new RegExp(stall.name) })).toBeVisible();
  }
  await makers.getByRole("link", { name: /Lucía/ }).click();

  await expect(page).toHaveURL("/stall/s_lucia");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Lucía");
});

test("a stall's second photo can be shown", async ({ page }) => {
  await page.goto("/stall/s_priya");

  await page.getByRole("button", { name: "Show photo 2" }).click();

  await expect(page.getByRole("article").getByRole("img", { name: /photo 2/ })).toBeVisible();
});

test("an unknown stall says so and links back to the makers", async ({ page }) => {
  await page.goto("/stall/s_nobody");

  await expect(page.getByRole("heading", { name: "No stall here" })).toBeVisible();
  await page.getByRole("link", { name: "See all the makers" }).click();
  await expect(page.getByRole("heading", { name: "Meet the makers" })).toBeVisible();
});

test("a stall fits a phone and a laptop screen", async ({ page }) => {
  for (const width of [375, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/stall/s_lucia");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Lucía");
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({ path: `e2e/screenshots/stall-${width}.png`, fullPage: true });
  }
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Meet the makers" }).getByRole("link")).toHaveCount(5);
  await page.screenshot({ path: "e2e/screenshots/home-1280.png", fullPage: true });
});
