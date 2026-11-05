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

/**
 * The /demo page's live feed: everything the agents, the sellers and PayPal do, newest first. `scroll`: the list
 * scrolls inside its own box (the page's sidebar), so a long feed never pushes the rest of the page down.
 */
export function LiveActivity({ scroll = false }: { scroll?: boolean }) {
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
          tabIndex={scroll ? 0 : undefined}
          className={`mt-4 divide-y divide-border rounded-xl border border-border bg-surface ${
            scroll
              ? "max-h-[28rem] overflow-y-auto focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent xl:max-h-[calc(100vh-9rem)]"
              : "overflow-hidden"
          }`}
        >
          {events.map((event) => (
            <ActivityItem key={event.id} event={event} stacked={scroll} />
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

/** An event's label. A message in the web chat (a demo phone on /seller-chat) says so rather than "WhatsApp". */
export function categoryOf(event: FeedEvent): Category {
  const name = eventCategory(event.type);
  if (name === "message" && event.payload.channel === "web") return { label: "Web chat", tone: "neutral" };
  return CATEGORIES[name] ?? { label: name, tone: "neutral" };
}

/** One event. `stacked`, in a narrow sidebar: the time and the label on one line, the summary below at full width. */
function ActivityItem({ event, stacked = false }: { event: FeedEvent; stacked?: boolean }) {
  const category = categoryOf(event);
  if (stacked) {
    return (
      <li className="px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <time dateTime={event.created_at} className="font-mono text-xs text-muted tabular-nums">
            {clockTime(event.created_at)}
          </time>
          <Badge tone={category.tone}>{category.label}</Badge>
        </div>
        <p className="mt-1 text-sm leading-6 break-words">{event.summary}</p>
      </li>
    );
  }
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
