import path from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// Pay-on-proof in fake mode (prompt 51): the order is approved on the simulated PayPal page, then a simulated proof of
// shipping pays one maker's share, a partial capture of the order's one authorization, sent to her payout rail.
const SCREENSHOTS = path.join(__dirname, "screenshots");

async function freshOrder(request: APIRequestContext): Promise<string> {
  const response = await request.post(`${E2E_API_URL}/api/dev/story-orders`);
  expect(response.status()).toBe(201);
  return ((await response.json()) as { order_id: string }).order_id;
}

async function approveAtSimulatedPayPal(page: Page, orderId: string) {
  await page.goto(`/approve/${orderId}`);
  await expect(page.getByText("One PayPal authorization for $815.00. Each maker's share is captured when she ships.")).toBeVisible();
  await page.getByRole("button", { name: "Approve and pay with PayPal" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Simulated PayPal (test mode)");
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Simulated PayPal is holding $815.00" })).toBeVisible();
  await expect(page.getByText("Simulated PayPal confirmed every share.", { exact: true })).toBeVisible();
}

function row(page: Page, name: string) {
  return page.getByRole("list", { name: "Each maker's share" }).getByRole("listitem").filter({ hasText: name });
}

async function neverSaysConfirmedByPayPal(page: Page) {
  await expect(page.getByText("Confirmed by PayPal", { exact: true })).toHaveCount(0);
  expect(await page.locator("body").innerText()).not.toContain("Confirmed by PayPal");
}

for (const width of [1280, 375]) {
  test(`simulated proof pays Priya on proof, and the other makers stay reserved (${width}px)`, async ({
    page,
    request,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const orderId = await freshOrder(request);
    await approveAtSimulatedPayPal(page, orderId);

    // Each maker's rail before anyone ships.
    await expect(row(page, "Amina")).toContainText("Paid to her bank through Hyperwallet when she ships (simulated)");
    await expect(row(page, "Priya")).toContainText("Paid to PayPal when she ships (simulated)");
    await expect(row(page, "Lucía")).toContainText("Paid to PayPal when she ships (simulated)");
    await expect(row(page, "Grace")).toContainText("Paid to Venmo when she ships (simulated)");
    await expect(page.getByText("One PayPal authorization for $815.00. Each maker's share is captured when she ships.")).toBeVisible();

    // Every maker can be paid on proof, Amina too: through Hyperwallet, simulated (prompt 52).
    for (const name of ["Amina", "Priya", "Lucía", "Grace"]) {
      await expect(row(page, name).getByRole("button", { name: /Simulate proof of shipping/ })).toBeEnabled();
    }

    await row(page, "Priya").getByRole("button", { name: /Simulate proof of shipping/ }).click();

    const priya = row(page, "Priya");
    await expect(priya).toContainText("Paid on proof of shipping");
    await expect(priya).toContainText("Paid to PayPal (simulated)");
    // The ticks: simulated PayPal confirmed her capture and her payout, and says it is simulated.
    await expect(priya).toContainText("Confirmed by simulated PayPal");
    await expect(priya.locator('[data-rail="paypal"] svg')).toBeVisible();
    await expect(priya).toContainText("payout confirmed by simulated PayPal");
    await expect(priya.getByRole("button", { name: /Simulate proof/ })).toHaveCount(0);

    await expect(row(page, "Grace")).toContainText("Venmo");
    for (const name of ["Amina", "Lucía", "Grace"]) {
      await expect(row(page, name)).toContainText("Reserved, paid when she ships");
    }
    await expect(page.getByText("Simulated PayPal confirmed every share.", { exact: true })).toBeVisible();
    await neverSaysConfirmedByPayPal(page);

    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({ path: path.join(SCREENSHOTS, `pay-on-proof-${width}.png`), fullPage: true });

    // The receipt survives a reload: Priya is still paid, and nothing is paid twice.
    await page.reload();
    await expect(row(page, "Priya")).toContainText("Paid on proof of shipping");
    await expect(row(page, "Lucía")).toContainText("Reserved, paid when she ships");
    await neverSaysConfirmedByPayPal(page);
  });
}

test("Amina is paid on proof to her bank through Hyperwallet, simulated, with nothing for PayPal to confirm", async ({
  page,
  request,
}) => {
  const orderId = await freshOrder(request);
  await approveAtSimulatedPayPal(page, orderId);

  await row(page, "Amina").getByRole("button", { name: /Simulate proof of shipping/ }).click();

  const amina = row(page, "Amina");
  await expect(amina).toContainText("Paid on proof of shipping");
  await expect(amina).toContainText("Paid to her bank through Hyperwallet (simulated)");
  await expect(amina.locator('[data-rail="hyperwallet"] svg')).toHaveCount(0); // PayPal never confirms Hyperwallet
  await expect(amina).not.toContainText("payout confirmed");
  await neverSaysConfirmedByPayPal(page);
  await page.screenshot({ path: path.join(SCREENSHOTS, "pay-on-proof-hyperwallet-1280.png"), fullPage: true });

  await page.goto("/demo");
  await expect(page.getByRole("list", { name: "Activity, newest first" })).toContainText(
    "Amina was paid $216.00 on proof of shipping, to her bank through Hyperwallet (simulated)",
  );
});

test("the approval page shows each maker's rail chip", async ({ page, request }) => {
  const orderId = await freshOrder(request);
  await page.goto(`/approve/${orderId}`);

  await expect(row(page, "Amina")).toContainText("Paid to her bank through Hyperwallet when she ships (simulated)");
  await expect(row(page, "Priya")).toContainText("Paid to PayPal when she ships (simulated)");
  await expect(row(page, "Grace")).toContainText("Paid to Venmo when she ships (simulated)");
});
