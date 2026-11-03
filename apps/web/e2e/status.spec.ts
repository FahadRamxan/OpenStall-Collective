import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import type { StatusReport } from "../src/lib/api";

const ADAPTERS = ["LLM", "Speech to text", "Embedder", "Messenger", "Payment gateway", "Image search"];
const SCREENSHOTS = path.join(__dirname, "screenshots");

function adaptersTable(page: Page) {
  return page.getByRole("table", { name: "Adapters" });
}

/** The adapters table's row for one adapter, found by its row header. */
function adapterRow(page: Page, label: string) {
  return adaptersTable(page)
    .getByRole("row")
    .filter({ has: page.getByRole("rowheader", { name: label, exact: true }) });
}

function modeBadge(page: Page, label: string) {
  return page.getByRole("region", { name: "Mode" }).getByText(label, { exact: true });
}

test("the footer links to the status page", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("contentinfo").getByRole("link", { name: "System status" }).click();

  await expect(page).toHaveURL("/status");
  await expect(page).toHaveTitle("System status · OpenStall Collective");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("System status");
});

test("shows the API's fake mode, its version and every adapter as fake", async ({ page }) => {
  const [response] = await Promise.all([
    page.waitForResponse((reply) => new URL(reply.url()).pathname === "/api/status"),
    page.goto("/status"),
  ]);
  const report = (await response.json()) as StatusReport;
  expect(report.mode).toBe("fake");

  await expect(modeBadge(page, "Fake")).toBeVisible();
  await expect(page.getByRole("region", { name: "Mode" }).getByText(report.version, { exact: true })).toBeVisible();
  const paypal = page.getByRole("region", { name: "PayPal" });
  await expect(paypal.getByText("Fake", { exact: true })).toBeVisible();
  await expect(paypal).toContainText("Checkout runs on the simulated PayPal page.");
  const headers = adaptersTable(page).getByRole("rowheader");
  await expect(headers).toHaveCount(ADAPTERS.length);
  for (const [index, label] of ADAPTERS.entries()) {
    await expect(headers.nth(index)).toHaveAccessibleName(label);
    await expect(adapterRow(page, label).getByText("Fake", { exact: true })).toBeVisible();
  }
});

test("the API starts on a fresh database, migrates it, and the page shows every table", async ({ page }) => {
  // playwright.config.ts empties the e2e database before the API starts, so OK here means the start-up migration ran.
  const [response] = await Promise.all([
    page.waitForResponse((reply) => new URL(reply.url()).pathname === "/api/status"),
    page.goto("/status"),
  ]);
  const report = (await response.json()) as StatusReport;
  expect(report.database.status).toBe("ok");
  expect(Object.keys(report.database.tables)).toEqual(
    expect.arrayContaining(["sellers", "products", "orders", "order_parts", "events", "processed_webhooks"]),
  );

  const database = page.getByRole("region", { name: "Database" });
  await expect(database.getByText("OK", { exact: true })).toBeVisible();
  const rows = database.getByLabel("Rows per table");
  for (const table of Object.keys(report.database.tables)) {
    await expect(rows.getByText(table, { exact: true })).toBeVisible();
  }
});

test("in sandbox mode, names the missing keys, and fits a phone screen", async ({ page }) => {
  // The e2e API always runs in fake mode, so this test swaps in a sandbox answer. It keeps the real response's
  // headers, CORS included.
  await page.route("**/api/status", async (route) => {
    const response = await route.fetch();
    const report = (await response.json()) as StatusReport;
    const sandbox: StatusReport = {
      ...report,
      mode: "sandbox",
      adapters: report.adapters.map((adapter) => {
        if (adapter.name === "payment_gateway") return { ...adapter, status: "real", missing_keys: [] };
        if (adapter.name === "llm") return { ...adapter, status: "not built", missing_keys: [] };
        return { ...adapter, status: "missing key", missing_keys: adapter.keys };
      }),
    };
    await route.fulfill({ response, json: sandbox });
  });
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/status");

  await expect(modeBadge(page, "Sandbox")).toBeVisible();
  await expect(adapterRow(page, "Messenger").getByText("Missing key", { exact: true })).toBeVisible();
  await expect(adapterRow(page, "Messenger")).toContainText("Not set: TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN.");
  await expect(adapterRow(page, "LLM").getByText("Not built yet", { exact: true })).toBeVisible();
  await expect(adapterRow(page, "Payment gateway").getByText("Real", { exact: true })).toBeVisible();

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, "the page scrolls sideways").toBeLessThanOrEqual(0);
  await page.screenshot({ path: path.join(SCREENSHOTS, "status-sandbox-375.png"), fullPage: true });
});

test("when the API cannot be reached, says so and loads on Try again", async ({ page }) => {
  await page.route("**/api/status", (route) => route.abort("connectionrefused"));
  await page.goto("/status");

  const alert = page.getByRole("main").getByRole("alert");
  await expect(alert).toContainText("Could not load the status.");

  await page.unroute("**/api/status");
  await alert.getByRole("button", { name: "Try again" }).click();

  await expect(modeBadge(page, "Fake")).toBeVisible();
  await expect(alert).toBeHidden();
});
