import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TopUps } from "@/components/top-ups";
import type { Order, OrderPart, PartDrop, TopUp } from "@/lib/orders";

function part(name: string, extra: Partial<OrderPart> = {}): OrderPart {
  return {
    id: `op_${name.toLowerCase()}`,
    reference_id: "op_004",
    seller: { id: `s_${name.toLowerCase()}`, name, city: null, country: null },
    product_title: "Cushion cover",
    photo: null,
    quantity: 7,
    unit_price_usd: "29.00",
    amount_usd: "203.00",
    delivery_date: "2026-12-10",
    status: "authorized",
    notice: null,
    confirmed_by_paypal: false,
    attention: null,
    confirmation_source: "simulated",
    nothing_to_confirm: false,
    payout_rail: "paypal",
    payout_label: "Paid to PayPal when she ships (simulated)",
    payout_via_paypal: true,
    payout_confirmed: false,
    trust_score: "0.95",
    trust_data_source: "seeded_demo",
    ...extra,
  };
}

function dropped(topUpId: string | null, extra: Partial<PartDrop> = {}): OrderPart {
  const drop: PartDrop = { state: "dropped", asked_at: null, dropped_at: null, top_up_order_id: topUpId, ...extra };
  return part("Grace", { status: "released", drop });
}

const TOP_UP: TopUp = {
  id: "ord_top",
  status: "draft",
  total_usd: "206.50",
  units: 7,
  created_at: "2026-11-10T10:09:00Z",
  approved_at: null,
  replaces: { order_id: "ord_story", part_id: "op_grace", seller_name: "Grace", quantity: 7 },
  parts: [part("Noor", { status: "pending", unit_price_usd: "29.50", amount_usd: "206.50" })],
};

function order(parts: OrderPart[], topUps: TopUp[] = []): Order {
  return {
    id: "ord_story",
    status: "authorized",
    total_usd: "815.00",
    units: 40,
    created_at: "2026-11-10T10:00:00Z",
    approved_at: "2026-11-10T10:05:00Z",
    paypal_order_id: "FAKE-1",
    parent_order_id: null,
    request: null,
    parts,
    top_ups: topUps,
  };
}

describe("TopUps", () => {
  it("says who dropped out, that her share went back, and links the top-up for its approval", () => {
    render(<TopUps order={order([part("Priya"), dropped("ord_top")], [TOP_UP])} />);

    const healing = screen.getByRole("region", { name: "The order heals itself" });
    expect(healing).toHaveTextContent(
      "Grace could not make her 7 units: her $203.00 share went back to the buyer, never charged.",
    );
    expect(healing).toHaveTextContent("Noor can make all 7: top-up order ord_top, $206.50.");
    expect(healing).toHaveTextContent("Waiting for your approval");
    expect(screen.getByRole("link", { name: "Approve the top-up" })).toHaveAttribute("href", "/approve/ord_top");
  });

  it("on the receipt it speaks to the buyer, and an approved top-up links its own receipt", () => {
    const approved = { ...TOP_UP, status: "authorized" as const, units: 4 };

    render(<TopUps order={order([dropped("ord_top")], [approved])} you />);

    const healing = screen.getByRole("region", { name: "The order heals itself" });
    expect(healing).toHaveTextContent("her $203.00 share went back to you, never charged.");
    expect(healing).toHaveTextContent("Noor can make 4 of the 7: top-up order ord_top");
    expect(screen.getByRole("link", { name: "Open the top-up's receipt" })).toHaveAttribute(
      "href",
      "/approve/ord_top/return",
    );
  });

  it("says when her units are still being asked for, and when no other maker could take them", () => {
    const { unmount } = render(<TopUps order={order([dropped(null)])} />);
    expect(screen.getByText("OpenStall is asking the other makers' agents for her units…")).toBeInTheDocument();
    unmount();

    render(<TopUps order={order([dropped(null, { replan_failed: "no other maker can make her units" })])} />);
    expect(screen.getByText("No other maker could take them: no other maker can make her units.")).toBeInTheDocument();
  });

  it("shows nothing while no maker has dropped out", () => {
    const { container } = render(<TopUps order={order([part("Priya"), part("Grace")])} />);

    expect(container).toBeEmptyDOMElement();
  });
});
