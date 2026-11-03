import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OrderCard } from "@/components/order-card";
import type { EventStreamState } from "@/hooks/use-event-stream";
import type { FeedEvent } from "@/lib/events";
import type { Order } from "@/lib/orders";

const stream: EventStreamState = { events: [], connected: true, error: null };

vi.mock("@/hooks/use-event-stream", async (original) => ({
  ...(await original<typeof import("@/hooks/use-event-stream")>()),
  useEventStream: () => stream,
}));

const DRAFT = {
  id: "ord_7f3a",
  status: "draft",
  total_usd: "815.00",
  units: 40,
  created_at: "2026-11-10T10:00:00Z",
  approved_at: null,
  paypal_order_id: null,
  parent_order_id: null,
  request: null,
  parts: [{}, {}, {}, {}],
} as unknown as Order;

function mockOrders(...bodies: Order[][]) {
  const fetch = vi.fn();
  for (const body of bodies) fetch.mockResolvedValueOnce(Response.json(body));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function event(id: number, type: string): FeedEvent {
  return { id, type, entity_id: "ord_7f3a", summary: type, payload: {}, created_at: "2026-11-10T10:00:00Z" };
}

beforeEach(() => {
  stream.events = [];
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("OrderCard", () => {
  it("shows the latest draft order with its total and the link to its approval page", async () => {
    const fetch = mockOrders([DRAFT]);

    render(<OrderCard />);

    expect(screen.getByRole("heading", { name: "Order" })).toBeInTheDocument();
    expect(await screen.findByText("ord_7f3a")).toBeInTheDocument();
    expect(screen.getByText("40 units from 4 makers, $815.00")).toBeInTheDocument();
    expect(screen.getByText("Waiting for your approval")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the approval page" })).toHaveAttribute("href", "/approve/ord_7f3a");
    expect(fetch).toHaveBeenCalledWith("http://api.test/api/orders?limit=1", expect.anything());
  });

  it("loads again when an order is drafted or changes, and not for other events", async () => {
    const fetch = mockOrders([], [DRAFT]);
    const view = render(<OrderCard />);
    expect(await screen.findByText(/No order yet/)).toBeInTheDocument();

    stream.events = [event(5, "offer.accepted")];
    view.rerender(<OrderCard />);
    expect(fetch).toHaveBeenCalledTimes(1);

    stream.events = [event(6, "order.drafted"), ...stream.events];
    view.rerender(<OrderCard />);

    expect(await screen.findByText("ord_7f3a")).toBeInTheDocument();
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  });

  it("says when the latest order cannot be loaded", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    render(<OrderCard />);

    expect(screen.getByText("Loading the latest order…")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("The latest order could not be loaded");
  });
});
