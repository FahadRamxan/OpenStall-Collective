import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// The complete live demo page (prompt 43, spec 3.9): the whole story on /demo. The scripted buyer agent's request,
// the offers and the split, one approval at (simulated) PayPal, then each maker told on her own phone in her language,
// and a maker paid on proof, her tracking on the PayPal order, all followed live. Earlier spec files leave story orders
// reserved, so each test first releases them: this order is then each maker's only open share.
const SCREENSHOTS = path.join(__dirname, "screenshots");

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${E2E_API_URL}/api/dev/release-reserved-shares`)).ok()).toBeTruthy();
});

async function openLive(page: Page) {
  await page.goto("/demo");
  await expect(page.getByRole("status").filter({ hasText: /^Live$/ })).toBeVisible();
}

function controls(page: Page) {
  return page.getByRole("region", { name: "Run the story" });
}

function payments(page: Page) {
  return page.getByRole("region", { name: "Payments" });
}

function phone(page: Page, name: string) {
  return page.getByRole("article", { name: `${name}'s phone` });
}

function orderStep(page: Page, name: string) {
  return payments(page)
    .getByRole("list", { name: "The order's steps after approval" })
    .getByRole("listitem")
    .filter({ hasText: name });
}

test("the whole story on one page: the request, one approval, each maker told on her phone, one paid on proof", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await openLive(page);
  await expect(page.getByRole("navigation", { name: "The story on this page" }).getByRole("link")).toHaveCount(9);

  // The buyer agent asks; the page follows the new draft order.
  await controls(page).getByRole("button", { name: "Run the demo request" }).click();
  await expect(controls(page).getByRole("status")).toContainText("drafted: $815.00");
  const orderId = (await controls(page).getByRole("status").locator(".font-mono").textContent())?.trim() ?? "";
  expect(orderId).toMatch(/^ord_/);
  await expect(payments(page)).toContainText(orderId);
  await expect(payments(page)).toContainText("Nothing is reserved yet");

  // The person approves at simulated PayPal.
  await controls(page).getByRole("link", { name: "Open its approval page" }).click();
  await page.getByRole("button", { name: "Approve and pay with PayPal" }).click();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Simulated PayPal is holding $815.00" })).toBeVisible();
  await expect(page.getByText("Each maker has been told about her share, in her own language.")).toBeVisible();

  // Back on the live demo: the money is held, and each phone has her order in her language.
  await openLive(page);
  await expect(payments(page)).toContainText(
    "$815.00 reserved at simulated PayPal. Nothing is captured yet: each maker is paid when she proves she shipped.",
  );
  await expect(orderStep(page, "Reserved at PayPal")).toHaveAttribute("data-state", "done");
  await expect(orderStep(page, "Makers told")).toHaveAttribute("data-state", "done");
  await expect(orderStep(page, "Paid on proof")).toHaveAttribute("data-state", "now");
  await expect(phone(page, "Priya")).toContainText(`ऑर्डर: ${orderId}`);
  await expect(phone(page, "Amina")).toContainText(`آرڈر: ${orderId}`);
  await expect(phone(page, "Lucía")).toContainText(`Pedido: ${orderId}`);
  await expect(phone(page, "Grace")).toContainText(`Order: ${orderId}`);
  await expect(phone(page, "Amina")).toContainText("Speaks Urdu");

  // Priya, played in test mode from her phone: her courier receipt, then her yes, in Hindi.
  await phone(page, "Priya").getByRole("button", { name: /Send Priya's courier receipt/ }).click();
  await expect(phone(page, "Priya")).toContainText(`मैंने ऑर्डर ${orderId}`);
  await expect(phone(page, "Priya")).toContainText("ट्रैकिंग नंबर: EE123456789IN");
  // Her yes sits in its own direction-isolated span, so the button's name may have spaces around it.
  await phone(page, "Priya").getByRole("button", { name: /Reply\s*“\s*हाँ\s*”\s*as Priya/ }).click();
  await expect(phone(page, "Priya")).toContainText(`आपको भुगतान हो गया! ऑर्डर ${orderId} के $176.00`);

  // Paid on proof, with her tracking on the PayPal order, and the live feed beside it says so.
  await expect(payments(page)).toContainText("$176.00 paid on proof to 1 maker");
  for (const name of ["Reserved at PayPal", "Makers told", "Paid on proof", "Tracking on PayPal"]) {
    await expect(orderStep(page, name)).toHaveAttribute("data-state", "done");
  }
  const priya = payments(page).getByRole("list", { name: "Each maker's payment" }).getByRole("listitem").filter({ hasText: "Priya" });
  await expect(priya).toContainText("Paid on proof of shipping");
  await expect(priya).toContainText("Tracking on the simulated PayPal order");
  const feed = page.getByRole("region", { name: "Live activity" });
  await expect(feed).toContainText("Priya was paid $176.00 on proof of shipping");
  await expect(feed).toContainText(`Priya's tracking (India Post EE123456789IN) is on simulated PayPal order`);
  // The feed sits beside the story on a wide screen.
  const feedBox = await feed.boundingBox();
  const paymentsBox = await payments(page).boundingBox();
  expect(feedBox && paymentsBox && feedBox.x > paymentsBox.x + paymentsBox.width - 1).toBeTruthy();
  await page.screenshot({ path: path.join(SCREENSHOTS, "live-demo-1280.png"), fullPage: true });
});

test("the live demo fits a phone screen, the feed after the story", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await openLive(page);

  await expect(payments(page)).toBeVisible();
  await expect(page.getByRole("region", { name: "The makers' phones" })).toBeVisible();
  const feed = await page.getByRole("region", { name: "Live activity" }).boundingBox();
  const phones = await page.getByRole("region", { name: "The makers' phones" }).boundingBox();
  expect(feed && phones && feed.y > phones.y).toBeTruthy();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: path.join(SCREENSHOTS, "live-demo-375.png"), fullPage: true });
});
