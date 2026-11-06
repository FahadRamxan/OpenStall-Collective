import path from "node:path";

import { expect, test } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// A real AI agent as the buyer (prompt 30). On /demo, "Run it with an AI agent" hands the story's request, in words, to
// a buyer's AI agent that chooses the MCP storefront's tools itself (test mode's stand-in here; Claude in sandbox
// mode). It ends with the approval link for its person, and the approval page says an AI agent asked for the order.
// Earlier spec files leave story orders reserved, so the test first releases them.
const SCREENSHOTS = path.join(__dirname, "screenshots");

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${E2E_API_URL}/api/dev/release-reserved-shares`)).ok()).toBeTruthy();
});

test("an AI agent chooses the storefront's tools and gets its person the approval link", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/demo");
  await expect(page.getByRole("status").filter({ hasText: /^Live$/ })).toBeVisible();
  const controls = page.getByRole("region", { name: "Run the story" });

  await controls.getByRole("button", { name: "Run it with an AI agent" }).click();

  const status = controls.getByRole("status");
  await expect(status).toContainText("The buyer's AI agent (test mode's stand-in for Claude) chose 4 tools:");
  await expect(status.getByRole("list", { name: "The tools the AI agent chose" }).getByRole("listitem")).toHaveText([
    /search_products: \d+ listings found/,
    /request_quote: Quote q_\w+: \d+ valid offers/,
    /create_collective_order: Order ord_\w+ drafted: \$815\.00/,
    "checkout: Approval link for the person",
  ]);
  await expect(status).toContainText("Approve it here, and PayPal only holds the money until each maker ships");
  // The stepper follows the AI agent's run as it follows the scripted one.
  const steps = controls.getByRole("list", { name: "The buyer agent's steps" }).getByRole("listitem");
  for (const step of await steps.all()) {
    await expect(step).toHaveAttribute("data-state", "done");
  }
  const feed = page.getByRole("region", { name: "Live activity" });
  await expect(feed).toContainText("A buyer's AI agent (test mode's stand-in for Claude) got a person's request");
  await expect(feed).toContainText("got its person the approval link");
  await page.screenshot({ path: path.join(SCREENSHOTS, "ai-buyer-1280.png"), fullPage: false });

  await status.getByRole("link", { name: "Open its approval page" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Approve this order" })).toBeVisible();
  await expect(page.getByText("Requested by an AI agent.")).toBeVisible();
});
