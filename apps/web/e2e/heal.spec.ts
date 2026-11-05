import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// The order heals itself (prompt 39). After the story's order is approved, Grace says on her phone that she cannot make
// her share, and confirms: her share goes back to the buyer, never charged; the other makers' agents are asked for her
// 7 units, and Noor's top-up order waits in Payments for the buyer's approval, which it gets like any order. Earlier
// spec files leave story orders reserved, so the test first releases them; it resets the demo world when it ends, as
// it leaves a top-up behind.
const SCREENSHOTS = path.join(__dirname, "screenshots");

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${E2E_API_URL}/api/dev/release-reserved-shares`)).ok()).toBeTruthy();
});

test.afterAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  expect((await api.post(`${E2E_API_URL}/api/demo/reset`)).ok()).toBeTruthy();
  await api.dispose();
});

function controls(page: Page) {
  return page.getByRole("region", { name: "Run the story" });
}

function payments(page: Page) {
  return page.getByRole("region", { name: "Payments" });
}

function phone(page: Page, name: string) {
  return page.getByRole("article", { name: `${name}'s phone` });
}

test("a maker drops out: her share goes back, and the other makers' top-up waits for the buyer's approval", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/demo");
  await expect(page.getByRole("status").filter({ hasText: /^Live$/ })).toBeVisible();

  // The story's order, drafted by the buyer agent and approved at simulated PayPal.
  await controls(page).getByRole("button", { name: "Run the demo request" }).click();
  await expect(controls(page).getByRole("status")).toContainText("drafted: $815.00");
  const orderId = (await controls(page).getByRole("status").locator(".font-mono").textContent())?.trim() ?? "";
  await controls(page).getByRole("link", { name: "Open its approval page" }).click();
  await page.getByRole("button", { name: "Approve and pay with PayPal" }).click();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Simulated PayPal is holding $815.00" })).toBeVisible();

  // Grace, played from her phone: she cannot make it, and is asked to confirm before anything moves.
  await page.goto("/demo");
  await expect(phone(page, "Grace")).toContainText(`Order: ${orderId}`);
  await phone(page, "Grace").getByRole("button", { name: /Grace can't make it/ }).click();
  await expect(phone(page, "Grace")).toContainText(`Do you want to give up your share of order ${orderId}`);
  await expect(payments(page).getByRole("region", { name: "The order heals itself" })).toHaveCount(0);

  // Her yes: her share goes back to the buyer, and Noor's agent takes her 7 units in a top-up order.
  await phone(page, "Grace").getByRole("button", { name: /Reply\s*“\s*Yes\s*”\s*as Grace/ }).click();
  await expect(phone(page, "Grace")).toContainText(`Done: your share of order ${orderId} goes back to the buyer`);
  const healing = payments(page).getByRole("region", { name: "The order heals itself" });
  await expect(healing).toContainText("Grace could not make her 7 units: her $203.00 share went back to the buyer");
  await expect(healing).toContainText("Noor can make all 7: top-up order");
  await expect(healing).toContainText("$206.50");
  const grace = payments(page)
    .getByRole("list", { name: "Each maker's payment" })
    .getByRole("listitem")
    .filter({ hasText: "Grace" });
  await expect(grace).toContainText("Released back to you");
  await expect(phone(page, "Noor")).toBeVisible();
  const feed = page.getByRole("region", { name: "Live activity" });
  await expect(feed).toContainText(`Grace dropped out of order ${orderId}`);
  await expect(feed).toContainText(`Order ${orderId} re-planned without Grace: Noor can make all 7 units she dropped`);
  await page.screenshot({ path: path.join(SCREENSHOTS, "heal-1280.png"), fullPage: false });

  // The buyer approves the top-up like any order: its own page says what it replaces.
  await healing.getByRole("link", { name: "Approve the top-up" }).click();
  await expect(page.getByText(`A top-up for order ${orderId}.`)).toBeVisible();
  await expect(page.getByText("Grace could not make her 7 units, so OpenStall asked the other makers")).toBeVisible();
  await page.getByRole("button", { name: "Approve and pay with PayPal" }).click();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Simulated PayPal is holding $206.50" })).toBeVisible();

  // Back on /demo, Noor has her order on her phone, in Urdu, and the top-up is reserved.
  await page.goto("/demo");
  await expect(phone(page, "Noor")).toContainText("آرڈر:");
  await expect(payments(page).getByRole("region", { name: "The order heals itself" })).toContainText("Reserved");
  await expect(
    payments(page).getByRole("region", { name: "The order heals itself" }).getByRole("link", { name: "Open the top-up's receipt" }),
  ).toBeVisible();
});
