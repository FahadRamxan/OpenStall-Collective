import { createHmac } from "node:crypto";
import { createRequire } from "node:module";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// What became of OpenStall's replies on WhatsApp, as Meta says after its 200 to the send (which only means it took
// them): a reply Meta could not deliver says so on the seller's chat, with Meta's reason, without a reload; one she
// read says Read. Meta's status callbacks are signed here with fake mode's public app secret (FAKE_META_APP_SECRET in
// apps/api/openstall_api/meta_whatsapp.py) and take the real webhook.
const FAKE_META_APP_SECRET = "openstall-fake-mode-meta-app-secret";
const LOCKED = {
  code: 131031,
  title: "Business Account locked",
  message: "Business Account locked",
  error_data: { details: "Business account has been locked." },
};
const AXE = createRequire(__filename).resolve("axe-core/axe.min.js");
const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

type Inbound = { seller_id: string; reply_whatsapp_ids: string[] };

/** As if Nasreen sent this on WhatsApp (fake mode's /api/dev/inbound takes the webhook's own path). */
async function sendOnWhatsApp(request: APIRequestContext, sender: string, text: string): Promise<Inbound> {
  const response = await request.post(`${E2E_API_URL}/api/dev/inbound`, {
    data: { sender, profile_name: "Nasreen", text },
  });
  expect(response.status()).toBe(201);
  return (await response.json()) as Inbound;
}

/** Meta's signed status for one of our messages, as its webhook sends it. */
async function metaSays(request: APIRequestContext, wamid: string, status: string, sender: string, errors?: object[]) {
  const update = { id: wamid, status, timestamp: "1762800002", recipient_id: sender.slice(1), ...(errors && { errors }) };
  const change = { field: "messages", value: { messaging_product: "whatsapp", statuses: [update] } };
  const body = JSON.stringify({ object: "whatsapp_business_account", entry: [{ id: "WABA", changes: [change] }] });
  const signature = `sha256=${createHmac("sha256", FAKE_META_APP_SECRET).update(body).digest("hex")}`;
  const response = await request.post(`${E2E_API_URL}/api/webhooks/whatsapp`, {
    data: body,
    headers: { "Content-Type": "application/json", "X-Hub-Signature-256": signature },
  });
  expect(response.status()).toBe(200);
}

async function violations(page: Page): Promise<string[]> {
  await page.addScriptTag({ path: AXE });
  return page.evaluate(async (tags) => {
    type Found = { id: string; help: string; nodes: { target: string[]; failureSummary?: string }[] };
    const axe = (window as unknown as { axe: { run: (c: unknown, o: unknown) => Promise<{ violations: Found[] }> } })
      .axe;
    const { violations: found } = await axe.run(document, { runOnly: { type: "tag", values: tags } });
    return found.map(
      (item) => `${item.id} at ${item.nodes[0]?.target.join(" ")}: ${item.nodes[0]?.failureSummary ?? item.help}`,
    );
  }, WCAG);
}

test("a reply WhatsApp could not deliver says why on her chat, live; one she read says Read", async ({
  page,
  request,
}) => {
  // Contrast is judged at rest, as in accessibility.spec.ts: bubbles and sections fade in otherwise.
  await page.emulateMedia({ reducedMotion: "reduce" });
  const sender = `+92302${String(Date.now()).slice(-7)}`;
  const first = await sendOnWhatsApp(request, sender, "Salaam");
  const [welcomeId] = first.reply_whatsapp_ids;
  expect(welcomeId).toBeTruthy();

  await page.goto(`/seller-chat?seller=${first.seller_id}`);
  const thread = page.getByRole("list", { name: "Messages with Nasreen" });
  const welcome = thread.getByRole("listitem").nth(1);
  await expect(welcome).toContainText("WhatsApp · Sent");

  await metaSays(request, welcomeId, "failed", sender, [LOCKED]);

  // No reload: the live feed's line makes her chat look again.
  await expect(welcome).toContainText("Not delivered");
  await expect(welcome).toContainText(
    "WhatsApp could not deliver it: (131031) Business Account locked: Business account has been locked.",
  );

  const second = await sendOnWhatsApp(request, sender, "I make cushion covers by hand");
  const answerId = second.reply_whatsapp_ids.at(-1) ?? "";
  await metaSays(request, answerId, "delivered", sender);
  await metaSays(request, answerId, "read", sender);
  await page.reload();
  await expect(thread.getByRole("listitem").last()).toContainText("WhatsApp · Read");
  await expect(welcome).toContainText("Not delivered");

  // The reason's colour is readable in both themes. Each is loaded afresh in its scheme, as accessibility.spec.ts
  // does: switched on an open page, colours would be judged halfway through their transition.
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
    await page.reload();
    await expect(welcome).toContainText("Not delivered");
    expect(await violations(page)).toEqual([]);
  }

  await page.goto("/demo");
  await expect(page.getByRole("list", { name: "Activity, newest first" })).toContainText(
    "WhatsApp could not deliver a message to Nasreen: (131031) Business Account locked",
  );
});
