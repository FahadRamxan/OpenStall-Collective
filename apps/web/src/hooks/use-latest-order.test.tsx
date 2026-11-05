import { render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EventStreamState } from "@/hooks/use-event-stream";
import { LatestOrderProvider, useLatestOrder } from "@/hooks/use-latest-order";
import type { FeedEvent } from "@/lib/events";
import type { Order } from "@/lib/orders";

const stream: EventStreamState = { events: [], connected: true, error: null };
vi.mock("@/hooks/use-event-stream", async (original) => ({
  ...(await original<typeof import("@/hooks/use-event-stream")>()),
  useEventStream: () => stream,
}));

const ORDER = { id: "ord_story", status: "authorized", parts: [] } as unknown as Order;

function event(id: number, type: string): FeedEvent {
  return { id, type, entity_id: null, summary: type, payload: {}, created_at: "2026-11-10T10:00:00Z" };
}

function Show() {
  const { order, error } = useLatestOrder();
  return <p>{error ?? (order === undefined ? "loading" : order === null ? "none" : order.id)}</p>;
}

beforeEach(() => {
  stream.events = [];
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("LatestOrderProvider", () => {
  it("loads the latest order once for every panel, and again when an order, a share or a tracking changes", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(Response.json([ORDER])));
    vi.stubGlobal("fetch", fetch);
    const view = render(
      <LatestOrderProvider>
        <Show />
        <Show />
      </LatestOrderProvider>,
    );

    expect(await screen.findAllByText("ord_story")).toHaveLength(2);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("http://api.test/api/orders?limit=1&top_ups=false");

    stream.events = [event(4, "offer.accepted")];
    view.rerender(
      <LatestOrderProvider>
        <Show />
      </LatestOrderProvider>,
    );
    expect(fetch).toHaveBeenCalledTimes(1);

    stream.events = [event(5, "tracking.added"), ...stream.events];
    view.rerender(
      <LatestOrderProvider>
        <Show />
      </LatestOrderProvider>,
    );
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  });

  it("says when there is no order, or when it cannot be loaded", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json([])));
    const view = render(
      <LatestOrderProvider>
        <Show />
      </LatestOrderProvider>,
    );
    expect(await screen.findByText("none")).toBeInTheDocument();
    view.unmount();

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    render(
      <LatestOrderProvider>
        <Show />
      </LatestOrderProvider>,
    );
    expect(await screen.findByText(/Could not reach the OpenStall API/)).toBeInTheDocument();
  });

  it("is needed around anything that uses the latest order", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => renderHook(() => useLatestOrder())).toThrow("useLatestOrder needs a LatestOrderProvider");
  });
});
