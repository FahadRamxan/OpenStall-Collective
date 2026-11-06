import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AdvanceLine } from "@/components/share-lines";
import type { OrderPart } from "@/lib/orders";

function part(advance: OrderPart["advance"]): OrderPart {
  return {
    id: "op_grace",
    reference_id: "op_004",
    seller: { id: "s_grace", name: "Grace", city: null, country: null },
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
    trust_score: "0.96",
    trust_data_source: "seeded_demo",
    advance,
  };
}

describe("AdvanceLine", () => {
  it("says an advance was paid by OpenStall, not the buyer, and labels simulated PayPal", () => {
    render(<AdvanceLine part={part({ state: "paid", amount_usd: "50.75", paid_at: "2026-11-10T10:00:00Z" })} simulated />);

    expect(
      screen.getByText("Advance for materials: $50.75, paid by OpenStall (simulated PayPal), not the buyer"),
    ).toBeInTheDocument();
  });

  it("says when one is offered or on its way, and nothing without one", () => {
    const { rerender, container } = render(
      <AdvanceLine part={part({ state: "asked", amount_usd: "50.75", paid_at: null })} simulated={false} />,
    );
    expect(screen.getByText("Advance for materials offered: $50.75")).toBeInTheDocument();

    rerender(<AdvanceLine part={part({ state: "accepted", amount_usd: "50.75", paid_at: null })} simulated={false} />);
    expect(screen.getByText("Advance for materials: $50.75, on its way")).toBeInTheDocument();

    rerender(<AdvanceLine part={part(null)} simulated={false} />);
    expect(container).toBeEmptyDOMElement();
  });
});
