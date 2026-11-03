import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MAX_EVENTS, type EventStreamState } from "@/hooks/use-event-stream";
import { useLiveList, type LiveListSource } from "@/hooks/use-live-list";
import type { FeedEvent } from "@/lib/events";

const stream: EventStreamState = { events: [], connected: true, error: null };

vi.mock("@/hooks/use-event-stream", async (original) => ({
  ...(await original<typeof import("@/hooks/use-event-stream")>()),
  useEventStream: () => stream,
}));

/** An order as a draft-order panel would show it: one row per order, changing as its events arrive. */
type OrderRow = { id: string; status: string; at: string };

let loadOrders: () => Promise<OrderRow[]>;

const ORDERS: LiveListSource<OrderRow> = {
  load: () => loadOrders(),
  fromEvent: (event) =>
    event.type.startsWith("order.") && event.entity_id
      ? { id: event.entity_id, status: event.type.slice("order.".length), at: event.created_at }
      : null,
  key: (order) => order.id,
  time: (order) => order.at,
  limit: 3,
};

const at = (minute: number) => `2026-11-10T10:${String(minute).padStart(2, "0")}:00Z`;

function orderEvent(id: number, order: string, status: string, minute: number): FeedEvent {
  return { id, type: `order.${status}`, entity_id: order, summary: "", payload: {}, created_at: at(minute) };
}

/** Events of a kind the panel does not show, newest first, as the stream keeps them. */
function otherEvents(fromId: number, count: number): FeedEvent[] {
  return Array.from({ length: count }, (_, n) => ({
    id: fromId + count - 1 - n,
    type: "message.received",
    entity_id: null,
    summary: "",
    payload: {},
    created_at: at(59),
  }));
}

/** The stream's list after `incoming` (newest first) arrives: newest first, at most MAX_EVENTS. */
function arrive(incoming: FeedEvent[]) {
  stream.events = [...incoming, ...stream.events].slice(0, MAX_EVENTS);
}

function statuses(rows: OrderRow[]) {
  return rows.map((order) => `${order.id} ${order.status}`);
}

beforeEach(() => {
  stream.events = [];
  loadOrders = () => Promise.resolve([]);
});

describe("useLiveList", () => {
  it("keeps the latest event about a row, whatever order the stream's list is in", async () => {
    // Newest first, as the stream keeps them: the order was drafted, then authorized.
    arrive([orderEvent(2, "ord_1", "drafted", 1)]);
    arrive([orderEvent(9, "ord_1", "authorized", 5)]);

    const { result } = renderHook(() => useLiveList(ORDERS));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(statuses(result.current.rows)).toEqual(["ord_1 authorized"]);
  });

  it("does not let an older backlog event replace a row loaded fresh from the API", async () => {
    loadOrders = () => Promise.resolve([{ id: "ord_1", status: "authorized", at: at(5) }]);
    const { result, rerender } = renderHook(() => useLiveList(ORDERS));
    await waitFor(() => expect(result.current.loading).toBe(false));

    // The page's backlog arrives after the load: it still holds the order's older "drafted" event.
    arrive([orderEvent(2, "ord_1", "drafted", 1)]);
    rerender();
    expect(statuses(result.current.rows)).toEqual(["ord_1 authorized"]);

    // A newer event does replace it.
    arrive([orderEvent(10, "ord_1", "captured", 8)]);
    rerender();
    expect(statuses(result.current.rows)).toEqual(["ord_1 captured"]);
  });

  it("keeps a streamed row after its event drops off the stream's list", async () => {
    const { result, rerender } = renderHook(() => useLiveList(ORDERS));
    await waitFor(() => expect(result.current.loading).toBe(false));
    arrive([orderEvent(1, "ord_new", "drafted", 30)]);
    rerender();
    expect(statuses(result.current.rows)).toEqual(["ord_new drafted"]);

    arrive(otherEvents(2, MAX_EVENTS));
    rerender();

    expect(stream.events.some((event) => event.entity_id === "ord_new")).toBe(false);
    expect(statuses(result.current.rows)).toEqual(["ord_new drafted"]);
  });

  it("shows only the newest rows, up to the source's limit", async () => {
    loadOrders = () =>
      Promise.resolve([
        { id: "ord_b", status: "drafted", at: at(2) },
        { id: "ord_a", status: "drafted", at: at(1) },
      ]);
    arrive([orderEvent(4, "ord_d", "drafted", 4), orderEvent(3, "ord_c", "drafted", 3)]);

    const { result } = renderHook(() => useLiveList(ORDERS));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(statuses(result.current.rows)).toEqual(["ord_d drafted", "ord_c drafted", "ord_b drafted"]);
  });

  it("says which row arrived on the stream after the first load, and never a loaded one", async () => {
    let answer: (orders: OrderRow[]) => void = () => {};
    loadOrders = () =>
      new Promise<OrderRow[]>((resolve) => {
        answer = resolve;
      });
    arrive([orderEvent(1, "ord_old", "drafted", 1)]); // the backlog, before the load answers
    const { result, rerender } = renderHook(() => useLiveList(ORDERS));
    expect(result.current.arrived).toBeNull();

    await act(async () => answer([{ id: "ord_loaded", status: "drafted", at: at(2) }]));
    expect(result.current.loading).toBe(false);
    expect(result.current.arrived).toBeNull();

    arrive([orderEvent(5, "ord_new", "drafted", 7)]);
    rerender();
    expect(result.current.arrived).toEqual({ id: "ord_new", status: "drafted", at: at(7) });

    // A later event about a row already shown is not a new arrival.
    arrive([orderEvent(6, "ord_loaded", "authorized", 8)]);
    rerender();
    expect(result.current.arrived?.id).toBe("ord_new");
    expect(statuses(result.current.rows)).toEqual(["ord_loaded authorized", "ord_new drafted", "ord_old drafted"]);
  });

  it("says why the earlier rows could not be loaded, and still adds new ones", async () => {
    loadOrders = () => Promise.reject(new TypeError("Failed to fetch"));
    const { result, rerender } = renderHook(() => useLiveList(ORDERS));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe("Failed to fetch");
    expect(result.current.rows).toEqual([]);

    arrive([orderEvent(3, "ord_1", "drafted", 3)]);
    rerender();

    expect(statuses(result.current.rows)).toEqual(["ord_1 drafted"]);
  });
});
