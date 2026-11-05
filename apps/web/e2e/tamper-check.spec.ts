import path from "node:path";

import { expect, test } from "@playwright/test";

// The tamper check, shown live (prompt 38, spec 3.7: "changing one number makes verification fail, shown live"). On
// /demo, a maker's signed trust card is checked in the browser with OpenStall's public key (Web Crypto's Ed25519) and
// by OpenStall's own verify endpoint: valid as signed, not once one number is changed, and valid again put back.
const SCREENSHOTS = path.join(__dirname, "screenshots");

test("a trust card checks out, fails with one number changed, and checks out again put back", async ({ page }) => {
  await page.goto("/demo");
  const panel = page.getByRole("region", { name: "Check a trust passport" });
  await panel.scrollIntoViewIfNeeded();
  await panel.getByLabel("Maker").selectOption({ label: "Priya" });
  const card = panel.getByRole("form", { name: "Priya's trust card" });

  await expect(panel.getByText("Signature valid: OpenStall signed exactly this card.")).toBeVisible();
  await expect(panel.getByText(/Checked in your browser with OpenStall's public key: valid\./)).toBeVisible();
  await expect(panel.getByText(/OpenStall's own check: valid\./)).toBeVisible();
  await expect(panel.getByText(/Signed with a fixed test key/)).toBeVisible();

  await card.getByLabel("Orders delivered").fill("670");
  await card.getByRole("button", { name: "Check the signature" }).click();

  await expect(panel.getByText("Signature does not match: this card was changed after OpenStall signed it.")).toBeVisible();
  await expect(panel.getByText(/Checked in your browser with OpenStall's public key: does not match\./)).toBeVisible();
  await expect(panel.getByText(/OpenStall's own check: does not match\./)).toBeVisible();
  await page.screenshot({ path: path.join(SCREENSHOTS, "tamper-check.png"), fullPage: false });

  await card.getByRole("button", { name: "Put it back" }).click();
  await expect(panel.getByText("Signature valid: OpenStall signed exactly this card.")).toBeVisible();
  await expect(card.getByLabel("Orders delivered")).toHaveValue("67");
});
