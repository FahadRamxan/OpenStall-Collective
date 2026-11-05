import path from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";
import { connect, getProduct, getTrustCard } from "./support/mcp";

// A stall's "For AI agents" box and the feeds it links to on the e2e API (prompt 21). Every spec file shares one
// database, seeded once, and they run one at a time in name order. Before this one, approve.spec.ts only reserves
// copies of the story's order and demo-feed.spec.ts records test events; paying on proof and the seller chat come in
// later files. None of them changes a listing or a passport (only the seed writes those), so these tests read the
// seeded makers as they are.
const SCREENSHOTS = path.join(__dirname, "screenshots");
const MCP_URL = `${E2E_API_URL}/mcp`;
const NOOR_ENTRY = `${E2E_API_URL}/catalog/p_noor_cushion.json`;
const NOOR_CARD = `${E2E_API_URL}/passport/s_noor`;

function agentsBox(page: Page) {
  return page.getByRole("region", { name: "For AI agents" });
}

async function openNoorsStall(page: Page) {
  await page.goto("/stall/s_noor");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Noor");
  await expect(agentsBox(page)).toBeVisible();
}

/** Clicks a link and returns the response the browser navigated to. */
async function follow(page: Page, link: Locator, url: string) {
  const [response] = await Promise.all([page.waitForResponse((answer) => answer.url() === url), link.click()]);
  await expect(page).toHaveURL(url);
  return response;
}

test("a stall's catalog link opens its entry, which holds the product just as get_product gives it", async ({
  page,
  request,
}) => {
  await openNoorsStall(page);
  // What agents can do today: read and search her stall, not order from it yet.
  await expect(agentsBox(page)).toContainText(
    "Buyer agents can read Noor's stall as JSON, or search it through OpenStall's MCP server.",
  );
  const link = agentsBox(page).getByRole("link", { name: "Catalog entry: Chain-stitch embroidered cushion cover" });
  await expect(link).toHaveAttribute("href", NOOR_ENTRY);

  const response = await follow(page, link, NOOR_ENTRY);

  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toBe("application/json");
  const entry = await response.json();
  expect(entry).toMatchObject({
    product_id: "p_noor_cushion",
    seller_id: "s_noor",
    seller_name: "Noor",
    title: "Chain-stitch embroidered cushion cover",
    price_usd: 31,
    capacity_per_week: 3,
    ship_days: 5,
    data_source: "seeded_demo",
    trust: { score: 0.97, data_source: "seeded_demo" },
    trust_card_url: NOOR_CARD,
  });
  expect(entry.photos).toEqual([
    `${E2E_API_URL}/media/seed/noor-cushion-1.svg`,
    `${E2E_API_URL}/media/seed/noor-cushion-2.svg`,
  ]);
  // The browser shows the JSON itself.
  await expect(page.locator("body")).toContainText("p_noor_cushion");
  // An agent on MCP reads exactly the same listing.
  expect(await getProduct(request, "p_noor_cushion")).toEqual(entry);
  // Its photos are full URLs that serve the photo, with caching headers.
  const photo = await request.get(entry.photos[0]);
  expect(photo.status()).toBe(200);
  expect(photo.headers()["cache-control"]).toBe("public, max-age=3600");
});

test("the trust card link gives her passport with the signature pending, as get_trust_card does", async ({
  page,
  request,
}) => {
  await openNoorsStall(page);
  const box = agentsBox(page);
  await expect(box.getByText("Signature pending")).toBeVisible();
  const link = box.getByRole("link", { name: "Trust card: Noor's passport" });

  const card = await (await follow(page, link, NOOR_CARD)).json();

  expect(card).toEqual({
    seller_id: "s_noor",
    issued_at: "2026-11-01T00:00:00Z",
    orders_delivered: 25,
    on_time_rate: 0.96,
    dispute_rate: 0,
    photo_originality: 0.94,
    score: 0.97,
    data_source: "seeded_demo",
    live_deliveries: 0,
    signature: "pending",
  });
  expect(await getTrustCard(request, "s_noor")).toEqual(card);
});

test("the MCP server address copies with one click, and the page says Copied", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await openNoorsStall(page);
  const box = agentsBox(page);
  await expect(box.getByRole("group", { name: "MCP server address" })).toContainText(MCP_URL);

  await box.getByRole("button", { name: "Copy the MCP server address" }).click();

  await expect(box.getByRole("status")).toHaveText("Copied");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(MCP_URL);
});

test("the box links to catalog.json, and to llms.txt, which opens in the browser and names every tool", async ({
  page,
  request,
}) => {
  const tools = await connect(request);
  expect(tools).toEqual(expect.arrayContaining(["search_products", "get_product", "get_trust_card"]));
  await openNoorsStall(page);

  const catalogLink = agentsBox(page).getByRole("link", { name: "catalog.json" });
  const catalog = await follow(page, catalogLink, `${E2E_API_URL}/catalog.json`);
  // Kept for at most a minute, here and in the API.
  expect(catalog.headers()["cache-control"]).toMatch(/^public, max-age=([0-9]|[1-5][0-9]|60)$/);
  const feed = await catalog.json();
  expect(feed.mcp_url).toBe(MCP_URL);
  const noor = feed.products.find((product: { product_id: string }) => product.product_id === "p_noor_cushion");
  expect(noor).toEqual(await getProduct(request, "p_noor_cushion"));

  await page.goBack();
  await expect(agentsBox(page)).toBeVisible();
  await follow(page, agentsBox(page).getByRole("link", { name: "llms.txt" }), `${E2E_API_URL}/llms.txt`);

  const text = page.locator("body");
  await expect(text).toContainText("# OpenStall Collective");
  await expect(text).toContainText(`- MCP server: ${MCP_URL} (Streamable HTTP, no sign-in)`);
  for (const tool of tools) {
    await expect(text).toContainText(`- ${tool}(`);
  }
  await expect(text).toContainText("Its tools (none of them spends money):");
  await expect(text).toContainText("create_collective_order turns that plan into a draft order");
  await expect(text).toContainText("- No MCP tool captures, refunds or moves money.");
  await expect(text).toContainText(`[Catalog](${E2E_API_URL}/catalog.json)`);
  await expect(text).toContainText('every trust card\'s "signature" reads "pending"');
  await page.screenshot({ path: path.join(SCREENSHOTS, "llms-txt-1280.png"), fullPage: true });
});

test("the For AI agents box fits a phone and a laptop screen", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  for (const width of [1280, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await openNoorsStall(page);
    const box = agentsBox(page);
    await box.getByRole("button", { name: "Copy the MCP server address" }).click();
    await expect(box.getByRole("status")).toHaveText("Copied");

    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await box.screenshot({ path: path.join(SCREENSHOTS, `for-agents-${width}.png`) });
    await page.screenshot({ path: path.join(SCREENSHOTS, `stall-for-agents-${width}.png`), fullPage: true });
  }
});
