"use client";

import { Badge, type BadgeTone } from "@/components/badge";
import { useEventStream } from "@/hooks/use-event-stream";
import { clockTime, eventCategory, type FeedEvent } from "@/lib/events";

type Category = { label: string; tone: BadgeTone };

/** How each kind of event is labelled in the feed, by the part of its type before the dot. */
export const CATEGORIES: Record<string, Category> = {
  listing: { label: "Listing", tone: "accent" },
  search: { label: "Search", tone: "neutral" },
  quote: { label: "Quote", tone: "accent" },
  offer: { label: "Offer", tone: "neutral" },
  allocation: { label: "Split", tone: "accent" },
  order: { label: "Order", tone: "accent" },
  checkout: { label: "Approval", tone: "accent" },
  part: { label: "Payment", tone: "success" },
  topup: { label: "Top-up", tone: "warning" },
  advance: { label: "Advance", tone: "success" },
  payment: { label: "PayPal", tone: "success" },
  message: { label: "WhatsApp", tone: "neutral" },
  tracking: { label: "Tracking", tone: "neutral" },
  delivery: { label: "Delivery", tone: "success" },
  passport: { label: "Passport", tone: "accent" },
  security: { label: "Security", tone: "danger" },
  demo: { label: "Demo", tone: "warning" },
};

/** The /demo page's live feed: everything the agents, the sellers and PayPal do, newest first. */
export function LiveActivity() {
  const { events, connected, error } = useEventStream();
  return (
    <section aria-labelledby="activity-heading" className="mt-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="activity-heading" className="text-xl font-semibold tracking-tight">
          Live activity
        </h2>
        <LiveDot connected={connected} />
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-danger">
          Past activity could not be loaded: {error}
        </p>
      ) : null}
      {events.length === 0 ? (
        <p className="mt-4 rounded-xl border border-dashed border-border p-6 leading-7 text-muted">
          Nothing has happened yet. Everything the buyer agent, the sellers and PayPal do will appear here as it
          happens.
        </p>
      ) : (
        <ol
          aria-label="Activity, newest first"
          className="mt-4 divide-y divide-border overflow-hidden rounded-xl border border-border bg-surface"
        >
          {events.map((event) => (
            <ActivityItem key={event.id} event={event} />
          ))}
        </ol>
      )}
    </section>
  );
}

function LiveDot({ connected }: { connected: boolean }) {
  return (
    <p role="status" className="flex items-center gap-2 text-sm font-medium">
      <span
        aria-hidden="true"
        className={`size-2.5 rounded-full ${connected ? "animate-pulse bg-success" : "bg-muted"}`}
      />
      {connected ? "Live" : "Connecting…"}
    </p>
  );
}

function ActivityItem({ event }: { event: FeedEvent }) {
  const name = eventCategory(event.type);
  const category = CATEGORIES[name] ?? { label: name, tone: "neutral" };
  return (
    <li className="flex items-start gap-3 px-4 py-3 sm:gap-4 sm:px-5">
      <time dateTime={event.created_at} className="shrink-0 pt-0.5 font-mono text-xs text-muted tabular-nums">
        {clockTime(event.created_at)}
      </time>
      <p className="min-w-0 flex-1 leading-6 break-words">{event.summary}</p>
      <Badge tone={category.tone}>{category.label}</Badge>
    </li>
  );
}
