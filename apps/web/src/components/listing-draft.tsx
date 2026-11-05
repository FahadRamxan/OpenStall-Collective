import type { ReactNode } from "react";

import { Badge } from "@/components/badge";
import { formatUsd, mediaUrl } from "@/lib/catalog";
import type { ListingDraft } from "@/lib/chats";

/** How each listing field is named on the page, in the spec's order (3.1, "Required listing fields"). */
export const FIELD_LABELS = {
  title: "What it is",
  description: "Description",
  category: "Category",
  variants: "Colours or styles",
  price_usd: "Price",
  capacity_per_week: "How many a week",
  ship_days: "Delivery time",
  ship_from_city: "Ships from",
  photos: "Photos",
} as const;

/** Her limits (spec 3.3), asked once the listing is whole: only her own seller agent uses them. */
export const LIMIT_LABELS = {
  floor_price_usd: "Lowest price",
  min_lead_days: "Days to make an order",
} as const;

type Field = keyof typeof FIELD_LABELS | keyof typeof LIMIT_LABELS;

/**
 * A seller's listing as far as her chat has told it, before she confirms it: each field read so far, the words she
 * used for each number (so a wrong reading can be traced), and what OpenStall still has to ask, one question at a
 * time ("Asking now"); then her limits. Nothing here is live for buyers yet. `mine`: on your own demo phone, so it
 * says "your".
 */
export function ListingDraftCard({ draft, mine }: { draft: ListingDraft; mine: boolean }) {
  const whose = mine ? "your" : "her";
  const missing = new Set(draft.missing);
  const value: Record<Field, ReactNode> = {
    title: draft.title,
    description: draft.description,
    category: draft.category,
    variants: draft.variants.join(", "),
    price_usd: draft.price_usd ? `${formatUsd(draft.price_usd)} each` : null,
    capacity_per_week: draft.capacity_per_week !== null ? `${draft.capacity_per_week} a week` : null,
    ship_days: draft.ship_days !== null ? `${draft.ship_days} days to arrive` : null,
    ship_from_city: draft.ship_from_city,
    photos: draft.photos.length ? (
      <ul aria-label="Listing photos" className="flex flex-wrap gap-2">
        {draft.photos.map((url) => (
          <li key={url}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={mediaUrl(url)} alt="A listing photo" className="size-16 rounded-lg border border-border object-cover" />
          </li>
        ))}
      </ul>
    ) : null,
    floor_price_usd: draft.floor_price_usd ? `${formatUsd(draft.floor_price_usd)} each, for a big order` : null,
    min_lead_days: typeof draft.min_lead_days === "number" ? `${draft.min_lead_days} days at least` : null,
  };

  function rows(labels: Partial<Record<Field, string>>) {
    return (Object.entries(labels) as [Field, string][]).map(([field, label]) => {
      const words = draft.words[field];
      return (
        <div key={field} className="contents">
          <dt className="font-medium text-muted">{label}</dt>
          <dd className="min-w-0 break-words">
            {missing.has(field) ? (
              <span className="font-medium text-warning">{draft.asked === field ? "Asking now" : "Still to ask"}</span>
            ) : (
              value[field]
            )}
            {!missing.has(field) && words ? (
              <span className="mt-0.5 block text-xs text-muted">
                In {whose} words: <q dir="auto">{words}</q>
              </span>
            ) : null}
          </dd>
        </div>
      );
    });
  }

  return (
    <section
      aria-labelledby="draft-heading"
      className="mx-auto mt-4 max-w-xl rounded-2xl border border-border bg-surface p-4 sm:p-5"
    >
      <h3 id="draft-heading" className="flex flex-wrap items-center gap-2 font-semibold">
        {mine ? "Your listing so far" : "Her listing so far"} <Badge tone="neutral">Draft, not live yet</Badge>
      </h3>
      <p className="mt-1 text-sm leading-6 text-muted">
        Read from {whose} photos and words. A price or a number is only taken from what was said. OpenStall asks for
        what is missing, one question at a time, in {whose} language.
      </p>
      <dl className="mt-4 grid gap-x-4 gap-y-3 text-sm sm:grid-cols-[9rem_1fr]">{rows(FIELD_LABELS)}</dl>
      <h4 className="mt-5 font-semibold">{mine ? "Your limits" : "Her limits"}</h4>
      <p className="mt-1 text-sm leading-6 text-muted">
        Not shown to buyers: {whose} seller agent never offers less than this price, or a delivery sooner than these
        days allow.
      </p>
      <dl className="mt-3 grid gap-x-4 gap-y-3 text-sm sm:grid-cols-[9rem_1fr]">{rows(LIMIT_LABELS)}</dl>
    </section>
  );
}
