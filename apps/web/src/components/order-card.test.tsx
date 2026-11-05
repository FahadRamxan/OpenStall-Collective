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
    expect(fetch).toHaveBeenCalledWith("http://api.test/api/orders?limit=1&top_ups=false", expect.anything());
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

  it("says when the approval link was sent to the human, with the link", async () => {
    mockOrders([
      {
        ...DRAFT,
        approval_link: { url: "http://localhost:3000/approve/ord_7f3a", issued_at: "2026-11-10T10:01:00Z" },
      },
    ]);

    render(<OrderCard />);

    expect(await screen.findByText("Approval link sent to the human:")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "http://localhost:3000/approve/ord_7f3a" })).toHaveAttribute(
      "href",
      "http://localhost:3000/approve/ord_7f3a",
    );
  });

  it("once PayPal holds the order, says how many makers have been told, with a link to their chats", async () => {
    const notice = { state: "sent", channel: "web", language: "ur", at: "2026-11-10T10:06:00Z" };
    mockOrders([
      {
        ...DRAFT,
        status: "authorized",
        approved_at: "2026-11-10T10:05:00Z",
        parts: [
          { status: "authorized", notice },
          { status: "captured", notice },
          { status: "authorized", notice: null },
          { status: "released", notice: null }, // released before she could be told: not counted
        ],
      } as unknown as Order,
    ]);

    render(<OrderCard />);

    expect(await screen.findByText("Makers told: 2 of 3")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See their chats" })).toHaveAttribute("href", "/seller-chat");
  });

  it("says nothing about makers being told while the order is a draft", async () => {
    mockOrders([{ ...DRAFT, parts: [{ status: "pending", notice: null }] } as unknown as Order]);

    render(<OrderCard />);

    expect(await screen.findByText("ord_7f3a")).toBeInTheDocument();
    expect(screen.queryByText(/Makers told/)).not.toBeInTheDocument();
  });

  it("loads again when a maker is told about her share", async () => {
    const fetch = mockOrders([DRAFT], [DRAFT]);
    const view = render(<OrderCard />);
    expect(await screen.findByText("ord_7f3a")).toBeInTheDocument();

    stream.events = [event(7, "message.order_notice")];
    view.rerender(<OrderCard />);

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  });

  it("says when the latest order cannot be loaded", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    render(<OrderCard />);

    expect(screen.getByText("Loading the latest order…")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("The latest order could not be loaded");
  });
});
