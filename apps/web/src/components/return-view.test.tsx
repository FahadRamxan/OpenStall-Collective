import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReturnView } from "@/components/return-view";
import type { Order } from "@/lib/orders";

const params = { orderId: "ord_demo" };
vi.mock("next/navigation", () => ({ useParams: () => params }));

function share(name: string, quantity: number, price: string, amount: string, seller: string) {
  return {
    id: `op_${seller}`,
    reference_id: "op_001",
    seller: { id: seller, name, city: "Lahore", country: "PK" },
    product_title: "Hand-embroidered cushion cover",
    photo: null,
    quantity,
    unit_price_usd: price,
    amount_usd: amount,
    delivery_date: "2026-12-10",
    status: "authorized" as const,
    trust_score: "0.95",
    trust_data_source: "seeded_demo" as const,
  };
}

const RESERVED: Order = {
  id: "ord_demo",
  status: "authorized",
  total_usd: "392.00",
  units: 23,
  created_at: "2026-11-03T10:00:00Z",
  approved_at: "2026-11-03T10:05:00Z",
  paypal_order_id: "FAKE-1234",
  parent_order_id: null,
  request: null,
  parts: [share("Amina", 12, "18.00", "216.00", "s_amina"), share("Priya", 11, "16.00", "176.00", "s_priya")],
};

beforeEach(() => {
  params.orderId = "ord_demo";
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("ReturnView", () => {
  it("reserves the order on arrival and shows the receipt, each share reserved until she ships", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json(RESERVED));
    vi.stubGlobal("fetch", fetchMock);

    render(<ReturnView />);

    expect(screen.getByRole("status", { name: "Reserving the money at PayPal" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 1, name: "PayPal is holding $392.00" })).toBeInTheDocument();
    const shares = within(screen.getByRole("list", { name: "Each maker's share" })).getAllByRole("listitem");
    expect(shares).toHaveLength(2);
    expect(shares[0]).toHaveTextContent("Amina · Lahore, Pakistan");
    expect(shares[0]).toHaveTextContent("12 × $18.00 · ships by December 10, 2026");
    expect(shares[0]).toHaveTextContent("$216.00");
    for (const row of shares) expect(row).toHaveTextContent("Reserved, paid when she ships");
    expect(screen.getByText("PayPal order")).toHaveTextContent("FAKE-1234");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.test/api/orders/ord_demo/reserve");
    expect(init.method).toBe("POST");
  });

  it("when PayPal does not have the approval, says so and links back to the order, without Try again", async () => {
    const detail = "PayPal does not have your approval for this order yet. Go back to the order and approve it.";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail }, { status: 409 })));

    render(<ReturnView />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The money is not reserved yet");
    expect(alert).toHaveTextContent(detail);
    expect(within(alert).getByRole("link", { name: "Back to the order" })).toHaveAttribute("href", "/approve/ord_demo");
    expect(within(alert).queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("when PayPal does not answer, Try again reserves it", async () => {
    const detail = "PayPal did not answer, so nothing was reserved or paid. Try again in a moment.";
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ detail }, { status: 503 }))
      .mockResolvedValueOnce(Response.json(RESERVED));
    vi.stubGlobal("fetch", fetchMock);
    render(<ReturnView />);

    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("heading", { level: 1, name: "PayPal is holding $392.00" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("says there is no order when the API does not know the id", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail: "No." }, { status: 404 })));

    render(<ReturnView />);

    expect(await screen.findByRole("heading", { name: "No order here" })).toBeInTheDocument();
  });
});
