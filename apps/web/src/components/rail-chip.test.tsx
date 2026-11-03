import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RailChip } from "@/components/rail-chip";
import type { OrderPart } from "@/lib/orders";

const PRIYA: OrderPart = {
  id: "op_priya",
  reference_id: "op_002",
  seller: { id: "s_priya", name: "Priya", city: "Jaipur", country: "IN" },
  product_title: "Mirror-work embroidered cushion cover",
  photo: null,
  quantity: 11,
  unit_price_usd: "16.00",
  amount_usd: "176.00",
  delivery_date: "2026-12-10",
  status: "authorized",
  confirmed_by_paypal: true,
  attention: null,
  confirmation_source: "simulated",
  nothing_to_confirm: false,
  payout_rail: "paypal",
  payout_label: "Paid to PayPal (simulated)",
  payout_via_paypal: true,
  payout_confirmed: false,
  trust_score: "0.97",
  trust_data_source: "seeded_demo",
};

describe("RailChip", () => {
  it("names her rail, and says it is simulated in fake mode", () => {
    const { container } = render(<RailChip part={PRIYA} />);

    expect(screen.getByText("Paid to PayPal (simulated)")).toBeInTheDocument();
    expect(container.querySelector("[data-rail]")).toHaveAttribute("data-rail", "paypal");
    expect(container.querySelector("svg")).toBeNull(); // no tick until her payout is confirmed
  });

  it("says Venmo for a maker paid on Venmo", () => {
    render(<RailChip part={{ ...PRIYA, payout_rail: "venmo", payout_label: "Paid to Venmo (simulated)" }} />);

    expect(screen.getByText("Paid to Venmo (simulated)")).toBeInTheDocument();
  });

  it("is honest about a maker no rail can reach yet", () => {
    const { container } = render(
      <RailChip
        part={{ ...PRIYA, payout_rail: "unavailable", payout_label: "Payout rail not connected yet (Pakistan)" }}
      />,
    );

    expect(screen.getByText("Payout rail not connected yet (Pakistan)")).toBeInTheDocument();
    expect(container.querySelector("[data-rail]")).toHaveAttribute("data-rail", "unavailable");
  });

  it("draws the tick from payout_confirmed, and in fake mode never says Confirmed by PayPal", () => {
    const { container } = render(<RailChip part={{ ...PRIYA, status: "captured", payout_confirmed: true }} />);

    expect(container.querySelector("svg")).not.toBeNull();
    expect(container).toHaveTextContent("payout confirmed by simulated PayPal");
    expect(container.textContent?.toLowerCase()).not.toContain("confirmed by paypal");
  });

  it("on the real sandbox, a confirmed payout is PayPal's own", () => {
    const { container } = render(
      <RailChip
        part={{
          ...PRIYA,
          status: "captured",
          confirmation_source: "paypal_sandbox",
          payout_label: "Paid to PayPal",
          payout_confirmed: true,
        }}
      />,
    );

    expect(container).toHaveTextContent("Paid to PayPal, payout confirmed by PayPal");
  });
});
