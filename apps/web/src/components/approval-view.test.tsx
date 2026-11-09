import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApprovalView } from "@/components/approval-view";
import { goTo } from "@/lib/navigation";
import { formatDay, type Order } from "@/lib/orders";
import type { PayPalButtonsOptions } from "@/lib/stall-orders";

const params = { orderId: "ord_demo" };
const search = { params: new URLSearchParams() };
vi.mock("next/navigation", () => ({ useParams: () => params, useSearchParams: () => search.params }));
vi.mock("@/lib/navigation", () => ({ goTo: vi.fn() }));

const CHECKOUT = { paypal_order_id: "FAKE-1", approval_url: "http://localhost:3000/fake-paypal?token=FAKE-1" };
const FAKE_CONFIG = { mode: "fake", client_id: null, currency: "USD", intent: "authorize", venmo: true, pay_later: false, buyer_country: null };
const SANDBOX_CONFIG = { ...FAKE_CONFIG, mode: "sandbox", client_id: "made-up-client-id", buyer_country: "US" };

/** Answers by address: the order, how to show PayPal, and the checkout (a fresh copy each time, as a body reads once). */
function stubApi({ order = ORDER as object, config = FAKE_CONFIG as object, checkout }: { order?: object; config?: object; checkout?: Response } = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    void init;
    const path = new URL(String(input)).pathname;
    if (path === "/api/paypal/config") return Response.json(config);
    if (path.endsWith("/checkout")) return checkout ? checkout.clone() : Response.json(CHECKOUT);
    if (path.endsWith("/reserve")) return Response.json({ ...ORDER, status: "authorized" });
    return Response.json(order);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function checkoutCall(fetchMock: ReturnType<typeof stubApi>) {
  const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/checkout"));
  return call ? { url: String(call[0]), init: call[1] as RequestInit } : null;
}

function share(name: string, quantity: number, price: string, amount: string, seller: string) {
  return {
    id: `op_${seller}`,
    reference_id: "op_001",
    seller: { id: seller, name, city: "Lahore", country: "PK" },
    product_title: "Hand-embroidered cushion cover",
    photo: `/media/seed/${seller}.svg`,
    quantity,
    unit_price_usd: price,
    amount_usd: amount,
    delivery_date: "2026-12-10",
    status: "pending" as const,
    confirmed_by_paypal: true,
    attention: null,
    confirmation_source: "paypal_sandbox" as const,
    nothing_to_confirm: false,
    payout_rail: "paypal" as const,
    payout_label: "Paid to PayPal",
    payout_via_paypal: true,
    payout_confirmed: false,
    trust_score: "0.95",
    trust_data_source: "seeded_demo" as const,
  };
}

const ORDER: Order = {
  id: "ord_demo",
  status: "draft",
  total_usd: "392.00",
  units: 23,
  created_at: "2026-11-03T10:00:00Z",
  approved_at: null,
  paypal_order_id: null,
  parent_order_id: null,
  request: {
    summary: "40 hand-embroidered cushion covers for corporate gifts",
    quantity: 40,
    max_unit_price: "30.00",
    deadline: "2026-12-10",
    ship_to: "Chicago",
  },
  parts: [share("Amina", 12, "18.00", "216.00", "s_amina"), share("Priya", 11, "16.00", "176.00", "s_priya")],
};

beforeEach(() => {
  params.orderId = "ord_demo";
  search.params = new URLSearchParams();
  vi.mocked(goTo).mockClear();
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  delete window.paypal;
});

describe("ApprovalView", () => {
  it("shows what the agent asked for", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(ORDER)));

    render(<ApprovalView />);

    const request = await screen.findByRole("region", { name: "What your AI agent asked for" });
    expect(request).toHaveTextContent("40 hand-embroidered cushion covers for corporate gifts");
    expect(request).toHaveTextContent("At most $30.00 each");
    expect(request).toHaveTextContent("To Chicago by December 10, 2026");
  });

  it("says when an AI agent asked for the order, and not otherwise", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ ...ORDER, requested_by_agent: true })));
    const view = render(<ApprovalView />);
    expect(await screen.findByText("Requested by an AI agent.")).toBeInTheDocument();
    view.unmount();

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(ORDER)));
    render(<ApprovalView />);
    await screen.findByRole("region", { name: "What your AI agent asked for" });
    expect(screen.queryByText("Requested by an AI agent.")).not.toBeInTheDocument();
  });

  it("opens with why this split when the order has a plan in words, and without it otherwise", async () => {
    const explained: Order = {
      ...ORDER,
      request: {
        ...ORDER.request!,
        explanation: "The 40 units are split across 2 makers, cheapest valid offer first.",
        explanation_by: "Written from the plan by OpenStall's code.",
      },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(explained)));
    const view = render(<ApprovalView />);

    const why = await screen.findByRole("region", { name: "Why this split" });
    expect(why).toHaveTextContent("The 40 units are split across 2 makers, cheapest valid offer first.");
    expect(why).toHaveTextContent("Written from the plan by OpenStall's code.");
    view.unmount();

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(ORDER)));
    render(<ApprovalView />);
    await screen.findByRole("region", { name: "What your AI agent asked for" });
    expect(screen.queryByRole("region", { name: "Why this split" })).not.toBeInTheDocument();
  });

  it("lists each maker's share with her amount, delivery date and trust, then the total", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(ORDER)));

    render(<ApprovalView />);

    const shares = within(await screen.findByRole("list", { name: "Each maker's share" })).getAllByRole("listitem");
    expect(shares).toHaveLength(2);
    expect(shares[0]).toHaveTextContent("Amina · Lahore, Pakistan");
    expect(shares[0]).toHaveTextContent("12 × $18.00");
    expect(shares[0]).toHaveTextContent("$216.00");
    expect(shares[0]).toHaveTextContent("By December 10, 2026");
    expect(shares[0]).toHaveTextContent("Trust 0.95 (seeded)");
    expect(within(shares[0]).getByRole("link", { name: "Amina" })).toHaveAttribute("href", "/stall/s_amina");
    expect(screen.getByRole("heading", { name: "2 makers make it together" })).toBeInTheDocument();
    expect(screen.getByText("23 items from 2 makers")).toBeInTheDocument();
    expect(screen.getByText("$392.00")).toBeInTheDocument();
  });

  it("shows each maker's payout rail, and one authorization under the total", async () => {
    const order: Order = {
      ...ORDER,
      parts: [
        {
          ...ORDER.parts[0],
          confirmation_source: "simulated",
          payout_rail: "unavailable",
          payout_label: "Payout rail not connected yet (Pakistan)",
          payout_via_paypal: false,
        },
        { ...ORDER.parts[1], confirmation_source: "simulated", payout_label: "Paid to PayPal (simulated)" },
      ],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(order)));

    render(<ApprovalView />);

    const shares = within(await screen.findByRole("list", { name: "Each maker's share" })).getAllByRole("listitem");
    expect(shares[0]).toHaveTextContent("Payout rail not connected yet (Pakistan)");
    expect(shares[1]).toHaveTextContent("Paid to PayPal (simulated)");
    expect(
      screen.getByText("One PayPal authorization for $392.00. Each maker's share is captured when she ships."),
    ).toBeInTheDocument();
  });

  it("explains pay-on-proof, under the button and above it", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(ORDER)));

    render(<ApprovalView />);

    const proof = await screen.findByRole("region", { name: "You pay once. Each maker is paid when she ships." });
    expect(proof).toHaveTextContent("PayPal reserves $392.00. Nothing is taken yet.");
    const button = screen.getByRole("button", { name: "Approve and pay with PayPal" });
    expect(button).toBeEnabled();
    expect(button).toHaveAccessibleDescription(/PayPal reserves the total now. Each maker is paid when she ships./);
  });

  it("Approve creates the PayPal order and goes to PayPal", async () => {
    const fetchMock = stubApi();
    render(<ApprovalView />);

    fireEvent.click(await screen.findByRole("button", { name: "Approve and pay with PayPal" }));

    await vi.waitFor(() => expect(goTo).toHaveBeenCalledWith(CHECKOUT.approval_url));
    const call = checkoutCall(fetchMock);
    expect(call?.url).toBe("http://api.test/api/orders/ord_demo/checkout");
    expect(call?.init.method).toBe("POST");
    expect(JSON.parse(String(call?.init.body))).toEqual({}); // PayPal's own checkout: no funding named
    expect(screen.getByRole("button", { name: "Opening PayPal…" })).toBeDisabled();
  });

  it("offers Venmo in test mode: the order is made for Venmo and goes to the simulated Venmo page", async () => {
    const venmo = { paypal_order_id: "FAKE-V", approval_url: "http://localhost:3000/fake-paypal?token=FAKE-V" };
    const fetchMock = stubApi({ checkout: Response.json(venmo) });
    render(<ApprovalView />);

    const button = await screen.findByRole("button", { name: "Pay with simulated Venmo" });
    expect(button).toHaveAccessibleDescription("For buyers in the US. The money is held the same way, and each maker is paid when she ships.");
    fireEvent.click(button);

    await vi.waitFor(() => expect(goTo).toHaveBeenCalledWith(venmo.approval_url));
    expect(JSON.parse(String(checkoutCall(fetchMock)?.init.body))).toEqual({ funding: "venmo" });
  });

  it("offers no Venmo when OpenStall does not", async () => {
    const fetchMock = stubApi({ config: { ...FAKE_CONFIG, venmo: false } });
    render(<ApprovalView />);

    await screen.findByRole("button", { name: "Approve and pay with PayPal" });
    await vi.waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/api/paypal/config"))).toBe(true),
    );
    expect(screen.queryByText("Or pay with Venmo")).not.toBeInTheDocument();
  });

  it("in sandbox mode, draws PayPal's Venmo button: it makes the order for Venmo, then reserves it once approved", async () => {
    let options: PayPalButtonsOptions | null = null;
    const drawn = vi.fn().mockResolvedValue(undefined);
    window.paypal = {
      FUNDING: { PAYPAL: "paypal", VENMO: "venmo", PAYLATER: "paylater" },
      Buttons: (given) => {
        options = given;
        return { render: drawn, isEligible: () => true };
      },
    };
    const fetchMock = stubApi({ config: SANDBOX_CONFIG, checkout: Response.json({ paypal_order_id: "VENMO-1", approval_url: "" }) });
    render(<ApprovalView />);

    await vi.waitFor(() => expect(drawn).toHaveBeenCalled());
    expect(options!.fundingSource).toBe("venmo");
    expect(await options!.createOrder()).toBe("VENMO-1");
    expect(JSON.parse(String(checkoutCall(fetchMock)?.init.body))).toEqual({ funding: "venmo" });
    await options!.onApprove();
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/reserve") && init?.method === "POST")).toBe(true);
    expect(goTo).toHaveBeenCalledWith("/approve/ord_demo/return");
  });

  it("in sandbox mode, says so when PayPal does not offer Venmo here", async () => {
    window.paypal = { Buttons: () => ({ render: vi.fn(), isEligible: () => false }) };
    stubApi({ config: SANDBOX_CONFIG });
    render(<ApprovalView />);

    expect(await screen.findByText(/PayPal doesn.t offer Venmo here: it is for a buyer in the US paying a US business./)).toBeInTheDocument();
  });

  it("says why checkout failed and lets the human try again", async () => {
    const refusal = { detail: "PayPal did not answer, so nothing was reserved or paid. Try again in a moment." };
    stubApi({ checkout: Response.json(refusal, { status: 503 }) });
    render(<ApprovalView />);

    fireEvent.click(await screen.findByRole("button", { name: "Approve and pay with PayPal" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("PayPal did not answer, so nothing was reserved");
    expect(screen.getByRole("button", { name: "Approve and pay with PayPal" })).toBeEnabled();
    expect(goTo).not.toHaveBeenCalled();
  });

  it("after the human cancels at PayPal, says nothing was reserved, and Try again goes back", async () => {
    search.params = new URLSearchParams("cancelled=1");
    stubApi({ order: { ...ORDER, status: "awaiting_approval" } });
    render(<ApprovalView />);

    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent("You left PayPal before approving");
    expect(notice).toHaveTextContent("Nothing was reserved and nothing was taken.");
    fireEvent.click(within(notice).getByRole("button", { name: "Try again" }));

    await vi.waitFor(() => expect(goTo).toHaveBeenCalledWith(CHECKOUT.approval_url));
  });

  it("an order PayPal already holds links to its receipt instead of the button", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ ...ORDER, status: "authorized" })));

    render(<ApprovalView />);

    const receipt = await screen.findByRole("link", { name: "See the receipt" });
    expect(receipt).toHaveAttribute("href", "/approve/ord_demo/return");
    expect(screen.queryByRole("button", { name: "Approve and pay with PayPal" })).not.toBeInTheDocument();
  });

  it("says there is no order when the API does not know the id", async () => {
    params.orderId = "ord_nobody";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json({ detail: "There is no order called 'ord_nobody'." }, { status: 404 })),
    );

    render(<ApprovalView />);

    expect(await screen.findByRole("heading", { name: "No order here" })).toBeInTheDocument();
  });

  it("says when the order cannot be loaded, and loads it on Try again", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(Response.json(ORDER));
    vi.stubGlobal("fetch", fetchMock);

    render(<ApprovalView />);

    expect(await screen.findByRole("alert")).toHaveTextContent("This order could not be loaded");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Approve this order" })).toBeInTheDocument();
  });
});

describe("formatDay", () => {
  it("names the same day in every time zone", () => {
    expect(formatDay("2026-12-10")).toBe("December 10, 2026");
    expect(formatDay("not a date")).toBe("not a date");
  });
});
