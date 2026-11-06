import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AdvanceLine, DisputeLine } from "@/components/share-lines";
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

  it("labels a payout that was only recorded outside test mode: Venmo on the sandbox, and Hyperwallet", () => {
    render(
      <AdvanceLine
        part={part({ state: "paid", amount_usd: "54.00", paid_at: "2026-11-10T10:00:00Z", payout_simulated: true })}
        simulated={false}
      />,
    );

    expect(
      screen.getByText("Advance for materials: $54.00, paid by OpenStall (simulated payout), not the buyer"),
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

describe("DisputeLine", () => {
  it("says where a buyer's PayPal dispute stands, in the API's words", () => {
    const { rerender } = render(
      <DisputeLine
        part={{
          ...part(null),
          status: "captured",
          dispute: {
            dispute_id: "PP-D-1",
            reason: "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
            state: "resolved",
            outcome: "seller",
            words: "PayPal dispute (the parcel did not arrive): decided in her favour (simulated PayPal)",
          },
        }}
      />,
    );
    expect(
      screen.getByText("PayPal dispute (the parcel did not arrive): decided in her favour (simulated PayPal)"),
    ).toHaveClass("text-success");

    rerender(
      <DisputeLine
        part={{
          ...part(null),
          dispute: {
            dispute_id: "PP-D-2",
            reason: "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED",
            state: "needs_person",
            outcome: null,
            words: "PayPal dispute: the buyer says the item is not as described. Needs a person: why",
          },
        }}
      />,
    );
    expect(screen.getByText(/Needs a person/)).toHaveClass("text-danger");
  });

  it("shows nothing without a dispute", () => {
    const { container } = render(<DisputeLine part={part(null)} />);

    expect(container).toBeEmptyDOMElement();
  });
});
