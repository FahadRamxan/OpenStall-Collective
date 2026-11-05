import { describe, expect, it } from "vitest";

import { canonicalJson, verifyInBrowser } from "@/lib/passports";

// What packages/trust's canonical_json writes for this card, printed by Python: the browser must write the same bytes.
const PYTHON =
  '{"data_source":"seeded_demo","dispute_rate":0,"issued_at":"2026-11-01T00:00:00Z","live_deliveries":0,' +
  '"live_on_time":0,"note":{"a":"Lucía","b":1},"on_time_rate":0.96,"orders_delivered":25,"photo_originality":0.94,' +
  '"score":0.97,"seller_id":"s_noor"}';

const CARD = {
  signature: "ed25519:x",
  seller_id: "s_noor",
  issued_at: "2026-11-01T00:00:00Z",
  orders_delivered: 25,
  on_time_rate: 0.96,
  dispute_rate: 0.0,
  photo_originality: 0.94,
  score: 0.97,
  live_deliveries: 0,
  live_on_time: 0,
  data_source: "seeded_demo",
  note: { b: 1.0, a: "Lucía" },
};

function base64(bytes: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)));
}

function base64url(bytes: ArrayBuffer): string {
  return base64(bytes).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** A card signed the way OpenStall signs one, with a key made here. */
async function signed(card: Record<string, unknown>) {
  const keys = (await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"])) as CryptoKeyPair;
  const signature = await crypto.subtle.sign({ name: "Ed25519" }, keys.privateKey, new TextEncoder().encode(canonicalJson(card)));
  const publicKey = base64(await crypto.subtle.exportKey("raw", keys.publicKey));
  return { card: { ...card, signature: `ed25519:${base64url(signature)}` }, publicKey };
}

describe("canonicalJson", () => {
  it("writes exactly what OpenStall's canonical_json writes: sorted keys, no whitespace, no signature", () => {
    expect(canonicalJson(CARD)).toBe(PYTHON);
  });
});

describe("verifyInBrowser", () => {
  it("accepts a card exactly as signed, and refuses it with one number changed", async () => {
    const { card, publicKey } = await signed({ ...CARD, note: undefined });

    expect(await verifyInBrowser(card, publicKey)).toBe(true);
    expect(await verifyInBrowser({ ...card, on_time_rate: 0.99 }, publicKey)).toBe(false);
    expect(await verifyInBrowser({ ...card, signature: "pending" }, publicKey)).toBe(false);
  });

  it("refuses a card signed by another key", async () => {
    const { card } = await signed(CARD);
    const { publicKey: other } = await signed(CARD);

    expect(await verifyInBrowser(card, other)).toBe(false);
  });
});
