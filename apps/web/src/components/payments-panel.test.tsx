import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PaymentsPanel, orderSteps } from "@/components/payments-panel";
import type { LatestOrderState } from "@/hooks/use-latest-order";
import type { Order, OrderPart } from "@/lib/orders";

const latest: LatestOrderState = { order: undefined, error: null };
vi.mock("@/hooks/use-latest-order", () => ({ useLatestOrder: () => latest }));

const TOLD = { state: "sent" as const, channel: "web" as const, language: "hi", at: "2026-11-10T10:06:00Z" };

function share(name: string, seller: string, amount: string, extra: Partial<OrderPart> = {}): OrderPart {
  return {
    id: `op_${seller}`,
    reference_id: "op_001",
    seller: { id: seller, name, city: "Jaipur", country: "IN" },
    product_title: "Cushion cover",
    photo: null,
    quantity: 11,
    unit_price_usd: "16.00",
    amount_usd: amount,
    delivery_date: "2026-12-10",
    ship_by: "2026-11-30",
    status: "authorized",
    notice: TOLD,
    confirmed_by_paypal: true,
    attention: null,
    confirmation_source: "simulated",
    nothing_to_confirm: false,
    payout_rail: "paypal",
    payout_label: "Paid to PayPal when she ships (simulated)",
    payout_via_paypal: true,
    payout_confirmed: false,
    trust_score: "0.95",
    trust_data_source: "seeded_demo",
    tracking_on_paypal: false,
    ...extra,
  };
}

const RESERVED: Order = {
  id: "ord_story",
  status: "authorized",
  total_usd: "392.00",
  units: 23,
  created_at: "2026-11-10T10:00:00Z",
  approved_at: "2026-11-10T10:05:00Z",
  paypal_order_id: "FAKE-1",
  parent_order_id: null,
  request: null,
  parts: [share("Priya", "s_priya", "176.00"), share("Amina", "s_amina", "216.00")],
};

const PAID: Order = {
  ...RESERVED,
  status: "partly_shipped",
  parts: [
    share("Priya", "s_priya", "176.00", {
      status: "captured",
      carrier: "India Post",
      tracking_number: "EE123456789IN",
      tracking_on_paypal: true,
    }),
    share("Amina", "s_amina", "216.00"),
  ],
};

beforeEach(() => {
  Object.assign(latest, { order: undefined, error: null });
});

describe("orderSteps", () => {
  it("follows the order after approval: reserved, makers told, paid on proof, tracking on PayPal", () => {
    expect(orderSteps({ ...RESERVED, status: "draft", parts: RESERVED.parts.map((part) => ({ ...part, status: "pending", notice: null })) }).map((step) => step.done)).toEqual([
      false,
      false,
      false,
      false,
    ]);
    expect(orderSteps(RESERVED).map((step) => step.done)).toEqual([true, true, false, false]);
    expect(orderSteps(PAID).map((step) => step.done)).toEqual([true, true, true, true]);
  });

  it("waits for every maker still in the order to be told, and not for one who was released", () => {
    const waiting = { ...RESERVED, parts: [RESERVED.parts[0], { ...RESERVED.parts[1], notice: null }] };
    const released = { ...RESERVED, parts: [RESERVED.parts[0], { ...RESERVED.parts[1], status: "released" as const, notice: null }] };

    expect(orderSteps(waiting)[1].done).toBe(false);
    expect(orderSteps(released)[1].done).toBe(true);
  });
});

describe("PaymentsPanel", () => {
  it("shows where the money stands and each maker's payment, as the order is paid on proof", () => {
    latest.order = PAID;

    render(<PaymentsPanel />);

    const steps = within(screen.getByRole("list", { name: "The order's steps after approval" })).getAllByRole("listitem");
    expect(steps.map((step) => step.getAttribute("data-state"))).toEqual(["done", "done", "done", "done"]);
    expect(screen.getByText(/reserved at simulated PayPal/)).toHaveTextContent(
      "$392.00 reserved at simulated PayPal. $176.00 paid on proof to 1 maker.",
    );
    expect(screen.getByText("Each maker has been told about her share, in her own language.")).toBeInTheDocument();
    const rows = within(screen.getByRole("list", { name: "Each maker's payment" })).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("Priya · Jaipur, India");
    expect(rows[0]).toHaveTextContent("11 × $16.00 · ships by November 30, 2026, arrives by December 10, 2026");
    expect(rows[0]).toHaveTextContent("Paid on proof of shipping");
    expect(rows[0]).toHaveTextContent("Shipped with India Post: EE123456789IN");
    expect(rows[0]).toHaveTextContent("Tracking on the simulated PayPal order");
    expect(rows[1]).toHaveTextContent("Reserved, paid when she ships");
    expect(rows[1]).toHaveTextContent("Told in the web chat, in Hindi");
  });

  it("before anyone is paid, says nothing is captured yet", () => {
    latest.order = RESERVED;

    render(<PaymentsPanel />);

    expect(screen.getByText(/reserved at simulated PayPal/)).toHaveTextContent(
      "$392.00 reserved at simulated PayPal. Nothing is captured yet: each maker is paid when she proves she shipped.",
    );
    const steps = within(screen.getByRole("list", { name: "The order's steps after approval" })).getAllByRole("listitem");
    expect(steps[2]).toHaveAttribute("aria-current", "step");
  });

  it("before approval, says nothing is reserved yet", () => {
    latest.order = { ...RESERVED, status: "draft", parts: RESERVED.parts.map((part) => ({ ...part, status: "pending", notice: null })) };

    render(<PaymentsPanel />);

    expect(
      screen.getByText("Nothing is reserved yet: a person approves the order first, and PayPal then holds the total."),
    ).toBeInTheDocument();
  });

  it("says when there is no order yet, or when it cannot be loaded", () => {
    latest.order = null;
    const { rerender } = render(<PaymentsPanel />);
    expect(screen.getByText(/No order yet/)).toBeInTheDocument();

    Object.assign(latest, { order: undefined, error: "The API could not be reached." });
    rerender(<PaymentsPanel />);
    expect(screen.getByRole("alert")).toHaveTextContent("The latest order could not be loaded: The API could not be reached.");
  });
});
