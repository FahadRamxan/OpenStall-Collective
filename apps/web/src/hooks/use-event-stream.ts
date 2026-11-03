"use client";

import { createContext, createElement, useContext, useEffect, useState, type ReactNode } from "react";

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
 * new stream after RETRY_MS. An event that arrives twice is shown once. Inside an EventStreamProvider it is the
 * provider's stream; anywhere else it opens its own.
 */
export function useEventStream(): EventStreamState {
  const shared = useContext(SharedStream);
  const own = useStream(shared === null);
  return shared ?? own;
}

/** The stream itself. Disabled, it opens nothing and stays empty. */
function useStream(enabled: boolean): EventStreamState {
  const [events, setEvents] = useState<FeedEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const seen = new Set<number>();
    let lastId = 0;
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    function add(incoming: FeedEvent[]) {
      const fresh = incoming.filter((event) => !seen.has(event.id));
      if (fresh.length === 0) return;
      for (const event of fresh) {
        seen.add(event.id);
        lastId = Math.max(lastId, event.id);
      }
      // `incoming` is oldest first; the list is newest first.
      setEvents((current) => [...fresh.reverse(), ...current].slice(0, MAX_EVENTS));
    }

    function connect() {
      if (stopped) return;
      const stream = new EventSource(eventStreamUrl(lastId));
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

    return () => {
      stopped = true;
      controller.abort();
      source?.close();
      if (retry) clearTimeout(retry);
    };
  }, [enabled]);

  return { events, connected, error };
}
