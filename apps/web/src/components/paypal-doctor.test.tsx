import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PayPalDoctor } from "@/components/paypal-doctor";
import type { DoctorReport } from "@/lib/doctor";

const REPORT: DoctorReport = {
  mode: "sandbox",
  healthy: false,
  checks: [
    { name: "Where the money goes", status: "ok", detail: "PayPal's sandbox: no real money moves." },
    { name: "PayPal keys and token", status: "fail", detail: "Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env." },
    { name: "PayPal webhook", status: "skip", detail: "Needs a PayPal token first." },
    { name: "Makers' payout accounts", status: "warn", detail: "No sandbox PayPal account for Priya." },
  ],
  products: [
    {
      key: "orders",
      name: "Orders v2, intent AUTHORIZE",
      used_for: "One order for the buyer's whole total",
      calls: ["POST /v2/checkout/orders", "GET /v2/checkout/orders/{id}"],
      code: "packages/paypal/openstall_paypal/sandbox.py",
      state: "proven",
      state_words: "Proven on the sandbox",
      evidence: "Run on the sandbox on November 3",
      prompts: "10",
    },
    {
      key: "hyperwallet",
      name: "Hyperwallet",
      used_for: "Amina's payout to her bank account",
      calls: [],
      code: "packages/paypal/openstall_paypal/rails.py",
      state: "simulated",
      state_words: "Simulated",
      evidence: "No Hyperwallet account is connected",
      prompts: "52",
    },
  ],
};

function answer(body: unknown, status = 200) {
  return vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));
}

afterEach(() => vi.unstubAllGlobals());

describe("PayPalDoctor", () => {
  it("shows each check with its word, and says something failed", async () => {
    vi.stubGlobal("fetch", answer(REPORT));
    render(<PayPalDoctor />);

    const checks = await screen.findByRole("list", { name: "PayPal checks" });
    const rows = within(checks).getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      "OKWhere the money goesPayPal's sandbox: no real money moves.",
      "FailedPayPal keys and tokenSet PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env.",
      "SkippedPayPal webhookNeeds a PayPal token first.",
      "WarningMakers' payout accountsNo sandbox PayPal account for Priya.",
    ]);
    expect(screen.getByText("Something failed: see the checks marked Failed.")).toBeInTheDocument();
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toMatch(/\/api\/paypal\/doctor$/);
  });

  it("lists every PayPal product with how far it has got and why", async () => {
    vi.stubGlobal("fetch", answer({ ...REPORT, healthy: true }));
    render(<PayPalDoctor />);

    const table = await screen.findByRole("table", { name: "PayPal products" });
    const orders = within(table).getByRole("rowheader", { name: /Orders v2, intent AUTHORIZE/ });
    expect(orders).toHaveTextContent("POST /v2/checkout/orders · GET /v2/checkout/orders/{id}");
    const hyperwallet = within(table).getByRole("row", { name: /Hyperwallet/ });
    expect(hyperwallet).toHaveTextContent("Simulated");
    expect(hyperwallet).toHaveTextContent("No Hyperwallet account is connected");
    expect(screen.getByText("Nothing failed.")).toBeInTheDocument();
  });

  it("says so when the API cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    render(<PayPalDoctor />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not run the PayPal doctor:");
    expect(screen.queryByRole("table")).toBeNull();
  });
});
