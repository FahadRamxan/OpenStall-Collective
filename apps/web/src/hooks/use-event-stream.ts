"use client";

import { createContext, createElement, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { errorMessage } from "@/lib/api";
import { eventStreamUrl, getLatestEvents, type FeedEvent } from "@/lib/events";

/** The most events kept in memory; older ones drop off the end. */
export const MAX_EVENTS = 200;
/** How long to wait before opening a new stream once the browser has given up on the old one. */
export const RETRY_MS = 3_000;

export type EventStreamState = {
  /** Newest first. */
  events: FeedEvent[];
  /** Whether the live stream is open right now. */
  connected: boolean;
  /** Why the past events could not be loaded, if they could not. */
  error: string | null;
};

const SharedStream = createContext<EventStreamState | null>(null);

/**
 * One event stream for every live panel inside it, such as on /demo. Each panel still calls useEventStream(), and
 * inside the provider they all share this stream, so a page with many panels holds one connection to the API.
 */
export function EventStreamProvider({ children }: { children: ReactNode }) {
  const state = useStream(true);
  return createElement(SharedStream.Provider, { value: state }, children);
}

/**
 * The latest events, newest first, kept up to date from the API's event stream.
 *
 * It loads the recent events first, then follows the stream from the last one it has, so nothing falls in the gap.
 * The browser reconnects a dropped stream by itself and sends the last event id it saw; if it gives up, this opens a
 * new stream after RETRY_MS. An event that arrives twice is shown once. Back on a page Next.js kept (see useStream),
 * it follows the stream on from the newest event shown. Inside an EventStreamProvider it is the provider's stream;
 * anywhere else it opens its own.
 */
export function useEventStream(): EventStreamState {
  const shared = useContext(SharedStream);
  const own = useStream(shared === null);
  return shared ?? own;
}

/**
 * `incoming` added to `current`: newest first, each event once, at most MAX_EVENTS. `current` itself when nothing in
 * `incoming` is new, so a repeat does not render again. Event ids only grow (a demo reset keeps the event log).
 */
export function mergeEvents(current: FeedEvent[], incoming: FeedEvent[]): FeedEvent[] {
  const shown = new Set(current.map((event) => event.id));
  const fresh = incoming.filter((event) => {
    if (shown.has(event.id)) return false;
    shown.add(event.id);
    return true;
  });
  if (fresh.length === 0) return current;
  return [...fresh, ...current].sort((a, b) => b.id - a.id).slice(0, MAX_EVENTS);
}

/**
 * The stream itself. Disabled, it opens nothing and stays empty.
 *
 * Next.js keeps a page the visitor left (React's <Activity>): while it is hidden this effect's cleanup has run, and
 * when they come back the effect runs again with the same events. So the newest event id lives in a ref, which
 * outlives the effect, and a page that comes back follows the stream on from it instead of loading the latest
 * events again; mergeEvents shows each event once whatever arrives.
 */
function useStream(enabled: boolean): EventStreamState {
  const [events, setEvents] = useState<FeedEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const newest = useRef(0);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    function add(incoming: FeedEvent[]) {
      if (incoming.length === 0) return;
      for (const event of incoming) newest.current = Math.max(newest.current, event.id);
      setEvents((current) => mergeEvents(current, incoming));
    }

    function connect() {
      if (stopped) return;
      const stream = new EventSource(eventStreamUrl(newest.current));
      source = stream;
      stream.onopen = () => setConnected(true);
      stream.onmessage = (message: MessageEvent<string>) => {
        try {
          add([JSON.parse(message.data) as FeedEvent]);
        } catch {
          // A malformed message is skipped; the next one carries on.
        }
      };
      stream.onerror = () => {
        setConnected(false);
        // While the stream is CONNECTING the browser is already retrying. Once CLOSED, start a fresh one.
        if (stream.readyState === EventSource.CLOSED) {
          stream.close();
          retry = setTimeout(connect, RETRY_MS);
        }
      };
    }

    if (newest.current > 0) {
      // Back on a kept page: the stream sends everything after the newest event shown, the missed ones included.
      connect();
    } else {
      getLatestEvents(50, { signal: controller.signal })
        .then((page) => {
          setError(null);
          add(page.events);
        })
        .catch((reason: unknown) => {
          if (!controller.signal.aborted) setError(errorMessage(reason));
        })
        .finally(() => {
          if (!controller.signal.aborted) connect();
        });
    }

    return () => {
      stopped = true;
      controller.abort();
      source?.close();
      if (retry) clearTimeout(retry);
      // A kept page is hidden, not gone: it must not say Live while its stream is closed.
      setConnected(false);
    };
  }, [enabled]);

  return { events, connected, error };
}
