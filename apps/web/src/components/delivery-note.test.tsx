import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DeliveryProblem, deliveryWords } from "@/components/delivery-note";
import type { ChatMessage } from "@/lib/chats";

const REPLY: ChatMessage = {
  id: "cm_2",
  direction: "outbound",
  channel: "whatsapp",
  text: "Please send a photo of it.",
  media: [],
  created_at: "2026-11-10T17:20:00Z",
};
const LOCKED = "WhatsApp could not deliver it: (131031) Business Account locked: Business account has been locked.";

describe("deliveryWords", () => {
  it("says how far OpenStall's message got on WhatsApp, and nothing while that is not known", () => {
    expect(deliveryWords({ ...REPLY, delivery: "sent" })).toBe(" · Sent");
    expect(deliveryWords({ ...REPLY, delivery: "delivered" })).toBe(" · Delivered");
    expect(deliveryWords({ ...REPLY, delivery: "read" })).toBe(" · Read");
    expect(deliveryWords({ ...REPLY, delivery: "failed", delivery_error: LOCKED })).toBe(" · Not delivered");
    expect(deliveryWords({ ...REPLY, delivery: null })).toBe("");
    expect(deliveryWords({ ...REPLY, channel: "web" })).toBe("");
  });

  it("never marks a seller's own message", () => {
    expect(deliveryWords({ ...REPLY, direction: "inbound", delivery: "read" })).toBe("");
  });
});

describe("DeliveryProblem", () => {
  it("says why WhatsApp could not deliver it, in WhatsApp's words", () => {
    render(<DeliveryProblem message={{ ...REPLY, delivery: "failed", delivery_error: LOCKED }} />);

    expect(screen.getByText(LOCKED)).toHaveClass("text-danger");
  });

  it("shows nothing for a message that got there, or is on its way", () => {
    const { container } = render(
      <>
        <DeliveryProblem message={{ ...REPLY, delivery: "read" }} />
        <DeliveryProblem message={{ ...REPLY, delivery: "sent" }} />
        <DeliveryProblem message={REPLY} />
      </>,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
