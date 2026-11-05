import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TamperCheck } from "@/components/tamper-check";
import { canonicalJson } from "@/lib/passports";

const PRIYA = {
  seller_id: "s_priya",
  issued_at: "2026-11-01T00:00:00Z",
  orders_delivered: 67,
  on_time_rate: 0.97,
  dispute_rate: 0.01,
  photo_originality: 0.93,
  score: 0.96,
  live_deliveries: 0,
  live_on_time: 0,
  data_source: "seeded_demo",
};
const SELLERS = [
  { id: "s_priya", name: "Priya", city: "Jaipur", country: "IN", language: "hi", data_source: "seeded_demo" },
  { id: "s_noor", name: "Noor", city: "Manchester", country: "GB", language: "en", data_source: "seeded_demo" },
];

function base64(bytes: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)));
}

/** Priya's card signed with a key made here, and an API that answers as OpenStall's would. */
async function stubApi() {
  const keys = (await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"])) as CryptoKeyPair;
  const raw = await crypto.subtle.sign({ name: "Ed25519" }, keys.privateKey, new TextEncoder().encode(canonicalJson(PRIYA)));
  const signature = `ed25519:${base64(raw).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")}`;
  const card = { ...PRIYA, signature };
  const publicKey = base64(await crypto.subtle.exportKey("raw", keys.publicKey));
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/api/sellers")) return Response.json(SELLERS);
    if (url.endsWith("/passport/public-key")) return Response.json({ algorithm: "Ed25519", public_key: publicKey, test_mode: true });
    if (url.endsWith("/passport/s_priya")) return Response.json(card);
    if (url.endsWith("/passport/verify") && init?.method === "POST") {
      const sent = JSON.parse(String(init.body));
      const valid = canonicalJson(sent) === canonicalJson(card) && sent.signature === signature;
      return Response.json({ valid, seller_id: sent.seller_id, reason: valid ? "nothing changed" : "changed" });
    }
    return Response.json({ detail: "not found" }, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock };
}

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("TamperCheck", () => {
  it("checks her signed card in the browser and with OpenStall: valid, then not once a number changes", async () => {
    await stubApi();
    render(<TamperCheck />);

    expect(await screen.findByText("Signature valid: OpenStall signed exactly this card.")).toBeInTheDocument();
    expect(screen.getByText(/Checked in your browser with OpenStall's public key: valid\./)).toBeInTheDocument();
    expect(screen.getByText(/Signed with a fixed test key/)).toBeInTheDocument();

    const card = screen.getByRole("form", { name: "Priya's trust card" });
    fireEvent.change(within(card).getByLabelText("On-time rate"), { target: { value: "0.99" } });
    expect(screen.getByText("Changed. Check the signature again.")).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: "Check the signature" }));

    expect(
      await screen.findByText("Signature does not match: this card was changed after OpenStall signed it."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Checked in your browser with OpenStall's public key: does not match\./)).toBeInTheDocument();
    expect(screen.getByText(/OpenStall's own check: does not match\./)).toBeInTheDocument();

    fireEvent.click(within(card).getByRole("button", { name: "Put it back" }));
    expect(await screen.findByText("Signature valid: OpenStall signed exactly this card.")).toBeInTheDocument();
    expect(within(card).getByLabelText("On-time rate")).toHaveValue(0.97);
  });

  it("says so when the trust card cannot be loaded", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail: "down" }, { status: 503 })));

    render(<TamperCheck />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The trust card could not be loaded");
  });
});
