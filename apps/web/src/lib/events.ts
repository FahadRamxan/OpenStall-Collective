import { apiBaseUrl, apiGet } from "@/lib/api";

/** One entry in the event log, as GET /api/events and the stream send it. */
export type FeedEvent = {
  id: number;
  type: string;
  entity_id: string | null;
  /** One line of plain English, written when the event was recorded. */
  summary: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type EventPage = { events: FeedEvent[] };

/** The most recent events, oldest first. */
export function getLatestEvents(limit = 50, init: RequestInit = {}): Promise<EventPage> {
  return apiGet<EventPage>(`/api/events?limit=${limit}`, init);
}

/** The server-sent event stream of everything after `afterId`. */
export function eventStreamUrl(afterId: number): string {
  return `${apiBaseUrl()}/api/events/stream?after_id=${afterId}`;
}

/** The part of an event type before the dot, such as "order" in "order.authorized". */
export function eventCategory(type: string): string {
  return type.split(".", 1)[0];
}
