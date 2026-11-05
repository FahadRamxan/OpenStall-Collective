import { apiGet, apiPost } from "@/lib/api";

/** A maker's trust card: her signed passport, exactly as OpenStall signed it (GET /passport/{seller_id}). */
export type TrustCard = {
  seller_id: string;
  issued_at: string;
  orders_delivered: number;
  on_time_rate: number;
  dispute_rate: number;
  photo_originality: number;
  score: number;
  live_deliveries: number;
  live_on_time: number;
  data_source: string;
  signature: string;
};

/** The key that checks every passport (GET /passport/public-key). */
export type PassportKey = { algorithm: "Ed25519"; public_key: string; test_mode: boolean };

/** OpenStall's own answer to "did you sign exactly this?" (POST /passport/verify). */
export type Verdict = { valid: boolean; seller_id: string | null; reason: string };

export function getTrustCard(sellerId: string, init: RequestInit = {}): Promise<TrustCard> {
  return apiGet<TrustCard>(`/passport/${encodeURIComponent(sellerId)}`, init);
}

export function getPassportKey(init: RequestInit = {}): Promise<PassportKey> {
  return apiGet<PassportKey>("/passport/public-key", init);
}

export function verifyWithOpenStall(card: Record<string, unknown>): Promise<Verdict> {
  return apiPost<Verdict>("/passport/verify", card);
}

/**
 * The text a passport's signature covers, as OpenStall's canonical_json writes it (packages/trust): every field but
 * "signature", keys sorted at every level, no whitespace. JSON.stringify already writes text as UTF-8 rather than
 * escapes, and whole-number floats as integers (1.0 as 1), which is why the Python side does the same.
 */
export function canonicalJson(card: Record<string, unknown>): string {
  const content = Object.fromEntries(Object.entries(card).filter(([key]) => key !== "signature"));
  return JSON.stringify(sorted(content));
}

function sorted(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sorted);
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return Object.fromEntries(entries.map(([key, item]) => [key, sorted(item)]));
  }
  return value;
}

function fromBase64(text: string, url = false): Uint8Array<ArrayBuffer> {
  const standard = url ? text.replace(/-/g, "+").replace(/_/g, "/") : text;
  const padded = standard + "=".repeat((4 - (standard.length % 4)) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

/**
 * Checks a card's signature here, in the browser, with OpenStall's public key and the browser's own Ed25519 (Web
 * Crypto): nothing is asked of OpenStall. True or false; null when this browser has no Ed25519 to check with.
 */
export async function verifyInBrowser(card: Record<string, unknown>, publicKeyB64: string): Promise<boolean | null> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) return null;
  const signature = typeof card.signature === "string" ? card.signature : "";
  if (!signature.startsWith("ed25519:")) return false;
  let key: CryptoKey;
  try {
    key = await subtle.importKey("raw", fromBase64(publicKeyB64), { name: "Ed25519" }, false, ["verify"]);
  } catch {
    return null; // no Ed25519 in this browser
  }
  try {
    return await subtle.verify(
      { name: "Ed25519" },
      key,
      fromBase64(signature.slice("ed25519:".length), true),
      new TextEncoder().encode(canonicalJson(card)),
    );
  } catch {
    return false; // a signature of the wrong length, for one
  }
}
