import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApprovalView } from "@/components/approval-view";
import { goTo } from "@/lib/navigation";
import { formatDay, type Order } from "@/lib/orders";

const params = { orderId: "ord_demo" };
const search = { params: new URLSearchParams() };
vi.mock("next/navigation", () => ({ useParams: () => params, useSearchParams: () => search.params }));
vi.mock("@/lib/navigation", () => ({ goTo: vi.fn() }));

const CHECKOUT = { paypal_order_id: "FAKE-1", approval_url: "http://localhost:3000/fake-paypal?token=FAKE-1" };

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
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(ORDER))
      .mockResolvedValueOnce(Response.json(CHECKOUT));
    vi.stubGlobal("fetch", fetchMock);
    render(<ApprovalView />);

    fireEvent.click(await screen.findByRole("button", { name: "Approve and pay with PayPal" }));

    await vi.waitFor(() => expect(goTo).toHaveBeenCalledWith(CHECKOUT.approval_url));
    const [url, init] = fetchMock.mock.calls[1];
    expect(url).toBe("http://api.test/api/orders/ord_demo/checkout");
    expect(init.method).toBe("POST");
    expect(screen.getByRole("button", { name: "Opening PayPal…" })).toBeDisabled();
  });

  it("says why checkout failed and lets the human try again", async () => {
    const refusal = { detail: "PayPal did not answer, so nothing was reserved or paid. Try again in a moment." };
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(Response.json(ORDER))
        .mockResolvedValueOnce(Response.json(refusal, { status: 503 })),
    );
    render(<ApprovalView />);

    fireEvent.click(await screen.findByRole("button", { name: "Approve and pay with PayPal" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("PayPal did not answer, so nothing was reserved");
    expect(screen.getByRole("button", { name: "Approve and pay with PayPal" })).toBeEnabled();
    expect(goTo).not.toHaveBeenCalled();
  });

  it("after the human cancels at PayPal, says nothing was reserved, and Try again goes back", async () => {
    search.params = new URLSearchParams("cancelled=1");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(Response.json({ ...ORDER, status: "awaiting_approval" }))
        .mockResolvedValueOnce(Response.json(CHECKOUT)),
    );
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
