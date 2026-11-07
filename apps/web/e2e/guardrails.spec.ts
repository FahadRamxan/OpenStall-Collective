import path from "node:path";

import { expect, test } from "@playwright/test";

// Try to break it (prompt 40): on /demo, every attack on the guardrail panel really tries what OpenStall must never
// allow, through the same code a real request goes through, and each is refused; the live feed records each refusal.
const SCREENSHOTS = path.join(__dirname, "screenshots");

test("every attack on the guardrail panel is refused, and the live feed says so", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/demo");
  await expect(page.getByRole("status").filter({ hasText: /^Live$/ })).toBeVisible();
  const panel = page.getByRole("region", { name: "Try to break it" });
  await panel.scrollIntoViewIfNeeded();
  const attacks = panel.getByRole("list", { name: "Attacks" }).getByRole("listitem");
  await expect(attacks).toHaveCount(9);

  await panel.getByRole("button", { name: "Try every attack" }).click();

  await expect(panel.getByRole("status")).toHaveText("9 of 9 attacks refused");
  for (const row of await attacks.all()) {
    await expect(row.getByText("Refused", { exact: true })).toBeVisible();
  }
  const floor = panel.getByRole("listitem", { name: "Talk a maker's price down to $1.00" });
  await expect(floor).toContainText("Refused by code (below_floor): her lowest price is $");
  const capture = panel.getByRole("listitem", { name: "An AI agent captures the payment through MCP" });
  await expect(capture).toContainText("Refused: there is no such tool.");
  const total = panel.getByRole("listitem", { name: "Send a smaller total than the order's" });
  await expect(total).toContainText("Totals are worked out on the server.");
  const webhook = panel.getByRole("listitem", { name: "Forge a PayPal webhook that says the money was captured" });
  await expect(webhook).toContainText("Refused: PayPal did not sign this event. Nothing changed.");
  const passport = panel.getByRole("listitem", { name: "Raise a maker's on-time rate on her trust card" });
  await expect(passport).toContainText("Refused: the signature does not match.");
  const flood = panel.getByRole("listitem", { name: "Flood the MCP storefront from one address" });
  await expect(flood).toContainText("the other 30 got 429 Too Many Requests");
  const refund = panel.getByRole("listitem", { name: "An AI agent refunds a payment through PayPal's MCP server" });
  await expect(refund).toContainText("Refused before anything was sent (TOOL_REFUSED)");
  await page.screenshot({ path: path.join(SCREENSHOTS, "guardrails-1280.png"), fullPage: false });

  const feed = page.getByRole("region", { name: "Live activity" });
  await expect(feed).toContainText("Guardrail held: Talk a maker's price down to $1.00.");
  await expect(feed).toContainText("A PayPal webhook failed verification and was refused");

  // One attack at a time, too.
  await passport.getByRole("button", { name: "Try it: Raise a maker's on-time rate on her trust card" }).click();
  await expect(passport.getByText("Refused", { exact: true })).toBeVisible();
});
