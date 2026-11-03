"use client";

import { useEffect, useState } from "react";

import { useEventStream } from "@/hooks/use-event-stream";
import { errorMessage } from "@/lib/api";
import type { FeedEvent } from "@/lib/events";

/**
 * Where a live panel's rows come from. Define it once, outside the component, so it is the same object on every
 * render: the panel starts over whenever it changes.
 */
export type LiveListSource<Row> = {
  /** The most recent rows from the API, read once when the panel opens. */
  load: (init: RequestInit) => Promise<Row[]>;
  /** The row an event carries, or null for an event this panel does not show. */
  fromEvent: (event: FeedEvent) => Row | null;
  /** A row's id: a row that is both loaded and streamed is shown once. */
  key: (row: Row) => string;
  /**
   * When the row last changed, as an ISO time. Rows are shown newest first, and of two versions of one row the newer
   * is kept, so a row that changes (an order going from drafted to authorized) must give the time of its change.
   */
  time: (row: Row) => string;
  /** The most rows shown. */
  limit: number;
};

export type LiveListState<Row> = {
  /** Newest first. */
  rows: Row[];
  /** The first load has not answered yet. */
  loading: boolean;
  /** Why the earlier rows could not be loaded, if they could not. New ones still arrive. */
  error: string | null;
  /** The newest row that arrived on the stream after the first load answered, for screen readers to announce. */
  arrived: Row | null;
};

/** What the hook keeps between renders. */
type Kept<Row> = {
  source: LiveListSource<Row>;
  /** The event list read last, and the highest event id read: each event is read once. */
  events: readonly FeedEvent[];
  lastEventId: number;
  /** Newest first, at most source.limit. */
  rows: Row[];
  /** The first load has answered, with `error` if it failed. */
  loaded: boolean;
  error: string | null;
  arrived: Row | null;
};

/**
 * A live panel's rows: the recent ones from the API, then each new one as its event arrives on the event stream.
 * Put the panel inside an EventStreamProvider, so every panel on the page shares one stream.
 *
 * The rows are kept here, not rebuilt from the stream's events: the stream keeps only its latest MAX_EVENTS events,
 * and a row must not vanish when its event drops off the end.
 */
export function useLiveList<Row>(source: LiveListSource<Row>): LiveListState<Row> {
  const { events } = useEventStream();
  const [kept, setKept] = useState(() => readEvents(start(source), events));

  // New events (or a new source): read the events not read yet, while rendering, so no render shows stale rows.
  let next = kept.source === source ? kept : start(source);
  if (next.events !== events) next = readEvents(next, events);
  if (next !== kept) setKept(next);

  useEffect(() => {
    const controller = new AbortController();
    const settle = (change: (current: Kept<Row>) => Kept<Row>) =>
      setKept((current) => (current.source === source ? change(current) : current));
    source
      .load({ signal: controller.signal })
      .then((rows) => settle((current) => ({ ...current, rows: merge(source, current.rows, rows), loaded: true })))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          settle((current) => ({ ...current, loaded: true, error: errorMessage(reason) }));
        }
      });
    return () => controller.abort();
  }, [source]);

  return { rows: next.rows, loading: !next.loaded, error: next.error, arrived: next.arrived };
}

function start<Row>(source: LiveListSource<Row>): Kept<Row> {
  return { source, events: [], lastEventId: 0, rows: [], loaded: false, error: null, arrived: null };
}

/** Reads the events not read yet, oldest first, so the latest event about a row wins. */
function readEvents<Row>(kept: Kept<Row>, events: readonly FeedEvent[]): Kept<Row> {
  const { source } = kept;
  // `events` is newest first.
  const fresh = events.filter((event) => event.id > kept.lastEventId).reverse();
  const incoming = fresh.map((event) => source.fromEvent(event)).filter((row): row is Row => row !== null);
  const rows = incoming.length > 0 ? merge(source, kept.rows, incoming) : kept.rows;
  return {
    ...kept,
    events,
    lastEventId: fresh.reduce((highest, event) => Math.max(highest, event.id), kept.lastEventId),
    rows,
    // Rows from the backlog that arrive with the first load are not news; a new row at the top after it is.
    arrived: kept.loaded ? (newAtTop(source, kept.rows, rows) ?? kept.arrived) : kept.arrived,
  };
}

/**
 * `rows` with `incoming` added, newest first, at most source.limit. Of two rows with one key the newer stays, and on
 * a tie the incoming one: so an event older than a freshly loaded row does not replace it.
 */
function merge<Row>(source: LiveListSource<Row>, rows: readonly Row[], incoming: readonly Row[]): Row[] {
  const byKey = new Map(rows.map((row) => [source.key(row), row] as const));
  for (const row of incoming) {
    const key = source.key(row);
    const known = byKey.get(key);
    // A time that does not parse (NaN) never counts as older, so the incoming row wins.
    if (known === undefined || !(at(source, row) < at(source, known))) byKey.set(key, row);
  }
  return [...byKey.values()].sort((a, b) => newestFirst(source, a, b)).slice(0, source.limit);
}

/** The row now at the top, if it was not in the list before. */
function newAtTop<Row>(source: LiveListSource<Row>, before: readonly Row[], after: readonly Row[]): Row | null {
  const top = after[0];
  if (top === undefined) return null;
  const key = source.key(top);
  return before.some((row) => source.key(row) === key) ? null : top;
}

function at<Row>(source: LiveListSource<Row>, row: Row): number {
  return Date.parse(source.time(row));
}

function newestFirst<Row>(source: LiveListSource<Row>, a: Row, b: Row): number {
  const later = at(source, b) - at(source, a);
  // Same moment, or a time that does not parse (NaN): the key decides, so the order is the same on every render.
  return later || source.key(b).localeCompare(source.key(a));
}
