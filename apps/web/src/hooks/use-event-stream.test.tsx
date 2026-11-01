import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MAX_EVENTS, RETRY_MS, useEventStream } from "@/hooks/use-event-stream";
import type { FeedEvent } from "@/lib/events";

/** Stands in for the browser's EventSource, which jsdom lacks. Tests drive it by hand. */
class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: FakeEventSource[] = [];

  readyState = FakeEventSource.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }

  open() {
    this.readyState = FakeEventSource.OPEN;
    this.onopen?.(new Event("open"));
  }

  send(data: unknown) {
    this.onmessage?.(new MessageEvent("message", { data: typeof data === "string" ? data : JSON.stringify(data) }));
  }

  /** closed=false: the browser is retrying by itself. closed=true: it has given up. */
  fail(closed: boolean) {
    this.readyState = closed ? FakeEventSource.CLOSED : FakeEventSource.CONNECTING;
    this.onerror?.(new Event("error"));
  }

  close() {
    this.readyState = FakeEventSource.CLOSED;
  }
}

function event(id: number, summary = `event ${id}`): FeedEvent {
  return { id, type: "demo.test", entity_id: null, summary, payload: {}, created_at: "2026-11-01T10:00:00Z" };
}

function mockPastEvents(events: FeedEvent[]) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ events })));
}

function latestStream(): FakeEventSource {
  return FakeEventSource.instances[FakeEventSource.instances.length - 1];
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("useEventStream", () => {
  it("loads the past events newest first, then follows the stream from the last one", async () => {
    mockPastEvents([event(1), event(2)]);

    const { result } = renderHook(() => useEventStream());

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(result.current.events.map((item) => item.id)).toEqual([2, 1]);
    expect(latestStream().url).toBe("http://api.test/api/events/stream?after_id=2");
    expect(result.current.connected).toBe(false);
  });

  it("puts a streamed event at the top, says it is live, and shows a repeated event once", async () => {
    mockPastEvents([event(1)]);
    const { result } = renderHook(() => useEventStream());
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => latestStream().open());
    act(() => latestStream().send(event(2, "Order reserved")));
    act(() => latestStream().send(event(2, "Order reserved")));
    act(() => latestStream().send(event(1)));

    expect(result.current.connected).toBe(true);
    expect(result.current.events.map((item) => item.summary)).toEqual(["Order reserved", "event 1"]);
  });

  it("skips a malformed message and carries on", async () => {
    mockPastEvents([]);
    const { result } = renderHook(() => useEventStream());
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => latestStream().send("{not json"));
    act(() => latestStream().send(event(5)));

    expect(result.current.events.map((item) => item.id)).toEqual([5]);
  });

  it("while the browser retries by itself, it shows Connecting and opens no second stream", async () => {
    mockPastEvents([]);
    const { result } = renderHook(() => useEventStream());
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    vi.useFakeTimers();

    act(() => latestStream().open());
    act(() => latestStream().fail(false));
    await act(() => vi.advanceTimersByTimeAsync(RETRY_MS * 2));

    expect(result.current.connected).toBe(false);
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("when the browser gives up, opens a new stream after a pause, from the last event it saw", async () => {
    mockPastEvents([event(1)]);
    renderHook(() => useEventStream());
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    vi.useFakeTimers();
    act(() => latestStream().send(event(7)));

    act(() => latestStream().fail(true));
    await act(() => vi.advanceTimersByTimeAsync(RETRY_MS - 1));
    expect(FakeEventSource.instances).toHaveLength(1);
    await act(() => vi.advanceTimersByTimeAsync(1));

    expect(FakeEventSource.instances).toHaveLength(2);
    expect(latestStream().url).toBe("http://api.test/api/events/stream?after_id=7");
  });

  it("says why the past events could not load, and still follows the stream", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const { result } = renderHook(() => useEventStream());

    await waitFor(() => expect(result.current.error).not.toBeNull());
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(latestStream().url).toBe("http://api.test/api/events/stream?after_id=0");
  });

  it(`keeps only the newest ${MAX_EVENTS} events`, async () => {
    mockPastEvents(Array.from({ length: MAX_EVENTS }, (_, index) => event(index + 1)));
    const { result } = renderHook(() => useEventStream());
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => latestStream().send(event(MAX_EVENTS + 1)));

    expect(result.current.events).toHaveLength(MAX_EVENTS);
    expect(result.current.events[0].id).toBe(MAX_EVENTS + 1);
    expect(result.current.events.at(-1)?.id).toBe(2);
  });

  it("closes the stream when the page goes away", async () => {
    mockPastEvents([]);
    const { unmount } = renderHook(() => useEventStream());
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    unmount();

    expect(latestStream().readyState).toBe(FakeEventSource.CLOSED);
  });
});
