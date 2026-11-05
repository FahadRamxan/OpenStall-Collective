import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LiveActivity } from "@/components/live-activity";
import type { EventStreamState } from "@/hooks/use-event-stream";
import type { FeedEvent } from "@/lib/events";

const state: EventStreamState = { events: [], connected: false, error: null };

vi.mock("@/hooks/use-event-stream", () => ({ useEventStream: () => state }));

function event(overrides: Partial<FeedEvent>): FeedEvent {
  return {
    id: 1,
    type: "demo.test",
    entity_id: null,
    summary: "A test event",
    payload: {},
    created_at: "2026-11-01T10:15:30Z",
    ...overrides,
  };
}

beforeEach(() => {
  Object.assign(state, { events: [], connected: false, error: null });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("LiveActivity", () => {
  it("says nothing has happened yet when there are no events", () => {
    render(<LiveActivity />);

    expect(screen.getByRole("heading", { name: "Live activity" })).toBeInTheDocument();
    expect(screen.getByText(/Nothing has happened yet/)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Activity, newest first" })).not.toBeInTheDocument();
  });

  it("lists events in the order given, each with its summary, time and category", () => {
    state.events = [
      event({ id: 2, type: "part.captured", summary: "Amina was paid $216.00 on proof" }),
      event({ id: 1, type: "order.authorized", summary: "Order reserved: $815.00 across 4 makers" }),
    ];

    render(<LiveActivity />);

    const items = within(screen.getByRole("list", { name: "Activity, newest first" })).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Amina was paid $216.00 on proof");
    expect(within(items[0]).getByText("Payment")).toBeInTheDocument();
    expect(within(items[1]).getByText("Order")).toBeInTheDocument();
    expect(items[0].querySelector("time")).toHaveAttribute("datetime", "2026-11-01T10:15:30Z");
  });

  it("labels a message by where it went: the web chat, or WhatsApp", () => {
    state.events = [
      event({
        id: 2,
        type: "message.order_notice",
        summary: "Priya was told about her share in the web chat, in Hindi: 11 to ship by November 30",
        payload: { channel: "web" },
      }),
      event({ id: 1, type: "message.received", summary: "Amina sent a photo on WhatsApp", payload: { channel: "whatsapp" } }),
    ];

    render(<LiveActivity />);

    const items = within(screen.getByRole("list", { name: "Activity, newest first" })).getAllByRole("listitem");
    expect(within(items[0]).getByText("Web chat")).toBeInTheDocument();
    expect(within(items[1]).getByText("WhatsApp")).toBeInTheDocument();
  });

  it("shows an unknown category as its raw name", () => {
    state.events = [event({ type: "mystery.thing", summary: "Something new" })];

    render(<LiveActivity />);

    expect(screen.getByText("mystery")).toBeInTheDocument();
  });

  it("says Live while the stream is open and Connecting otherwise", () => {
    const { rerender } = render(<LiveActivity />);
    expect(screen.getByRole("status")).toHaveTextContent("Connecting…");

    state.connected = true;
    rerender(<LiveActivity />);

    expect(screen.getByRole("status")).toHaveTextContent("Live");
  });

  it("says when past activity could not be loaded", () => {
    state.error = "The API could not be reached.";

    render(<LiveActivity />);

    expect(screen.getByRole("alert")).toHaveTextContent("Past activity could not be loaded: The API could not be reached.");
  });
});
