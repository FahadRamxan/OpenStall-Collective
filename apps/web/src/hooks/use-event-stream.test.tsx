import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import { Activity } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EventStreamProvider, MAX_EVENTS, mergeEvents, RETRY_MS, useEventStream } from "@/hooks/use-event-stream";
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

  it("inside an EventStreamProvider, every panel shares the provider's one stream", async () => {
    mockPastEvents([event(1)]);
    function Panel({ name }: { name: string }) {
      const { events, connected } = useEventStream();
      return (
        <p>
          {name}: {events.map((item) => item.id).join(",")} {connected ? "live" : "connecting"}
        </p>
      );
    }

    const { unmount } = render(
      <EventStreamProvider>
        <Panel name="searches" />
        <Panel name="activity" />
      </EventStreamProvider>,
    );
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => latestStream().open());
    act(() => latestStream().send(event(2)));

    expect(screen.getByText("searches: 2,1 live")).toBeInTheDocument();
    expect(screen.getByText("activity: 2,1 live")).toBeInTheDocument();
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(fetch).toHaveBeenCalledTimes(1);
    unmount();
    expect(latestStream().readyState).toBe(FakeEventSource.CLOSED);
  });

  it("back on a page Next.js kept, shows each event once and follows the stream on from the newest", async () => {
    // Next.js keeps a page the visitor left inside React's <Activity>: hidden, its effects stop and its state stays;
    // shown again, the effects run again. Loading the latest events again here showed every one of them twice.
    mockPastEvents([event(1), event(2)]);
    function Feed() {
      const { events, connected } = useEventStream();
      return (
        <p>
          feed: {events.map((item) => item.id).join(",")} {connected ? "live" : "connecting"}
        </p>
      );
    }
    const page = (mode: "visible" | "hidden") => (
      <Activity mode={mode}>
        <Feed />
      </Activity>
    );
    const { rerender } = render(page("visible"));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => latestStream().open());
    act(() => latestStream().send(event(3)));

    rerender(page("hidden"));
    expect(latestStream().readyState).toBe(FakeEventSource.CLOSED);
    rerender(page("visible"));

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
    expect(latestStream().url).toBe("http://api.test/api/events/stream?after_id=3");
    expect(screen.getByText("feed: 3,2,1 connecting")).toBeInTheDocument();
    act(() => latestStream().open());
    act(() => latestStream().send(event(3)));
    act(() => latestStream().send(event(4)));
    expect(screen.getByText("feed: 4,3,2,1 live")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

describe("mergeEvents", () => {
  it("adds the new events newest first, each once", () => {
    const merged = mergeEvents([event(5), event(2)], [event(3), event(6), event(6), event(2)]);

    expect(merged.map((item) => item.id)).toEqual([6, 5, 3, 2]);
  });

  it("gives back the same list when nothing is new, so nothing renders again", () => {
    const current = [event(2), event(1)];

    expect(mergeEvents(current, [event(1), event(2)])).toBe(current);
    expect(mergeEvents(current, [])).toBe(current);
  });

  it(`keeps the newest ${MAX_EVENTS}`, () => {
    const current = Array.from({ length: MAX_EVENTS }, (_, index) => event(MAX_EVENTS - index));

    const merged = mergeEvents(current, [event(MAX_EVENTS + 1)]);

    expect(merged).toHaveLength(MAX_EVENTS);
    expect(merged[0].id).toBe(MAX_EVENTS + 1);
    expect(merged.at(-1)?.id).toBe(2);
  });
});
