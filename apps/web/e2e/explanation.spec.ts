import { expect, test } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// The plan in words: fake mode's stand-in model explains the story's split, and code has checked every number in
// it. Reserved shares use up makers' capacity, and approve.spec.ts leaves story orders reserved in the same database,
// so each test first releases every reserved share.
const STORY_MAKERS = ["Priya", "Amina", "Lucía", "Grace"];

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${E2E_API_URL}/api/dev/release-reserved-shares`)).ok()).toBeTruthy();
});

test("the allocation is explained in words that name the 40 and all four makers", async ({ page, request }) => {
  expect((await request.post(`${E2E_API_URL}/api/dev/quote`)).status()).toBe(201);
  await page.goto("/demo");

  const words = page.getByRole("region", { name: "Allocation", exact: true }).getByLabel("The plan in words");
  await expect(words).toContainText("40");
  for (const maker of STORY_MAKERS) await expect(words).toContainText(maker);
  await expect(words).toContainText("$815.00");
  await expect(page.getByText("Written by the stand-in model of test mode; every number checked against the plan.")).toBeVisible();
});

test("the approval page opens with why this split", async ({ page }) => {
  await page.goto("/approve/ord_demo");

  const why = page.getByRole("region", { name: "Why this split" });
  await expect(why).toContainText("The 40 units are split across 4 makers, cheapest valid offer first");
  for (const maker of STORY_MAKERS) await expect(why).toContainText(maker);
  await expect(why).toContainText("Written from the plan by OpenStall's code.");
  // It comes before the request and the makers.
  const headings = await page.getByRole("heading", { level: 2 }).allTextContents();
  expect(headings[0]).toBe("Why this split");
});
