import Link from "next/link";

import { Badge } from "@/components/badge";
import { formatUsd } from "@/lib/catalog";
import type { LiveListing } from "@/lib/chats";

/**
 * A seller's listing once her yes published it from her chat (spec 3.1 step 6): live for buyers' AI agents in search,
 * the catalog and the MCP storefront, with a link to her stall. `mine`: on your own demo phone, so it says "your".
 */
export function LiveListingCard({ listing, mine }: { listing: LiveListing; mine: boolean }) {
  const whose = mine ? "your" : "her";
  return (
    <section
      aria-labelledby="live-listing-heading"
      className="mx-auto mt-4 max-w-xl rounded-2xl border border-border bg-surface p-4 sm:p-5"
    >
      <h3 id="live-listing-heading" className="flex flex-wrap items-center gap-2 font-semibold">
        {mine ? "Your listing is live" : "Her listing is live"} <Badge tone="success">Live</Badge>
      </h3>
      <p className="mt-1 text-sm leading-6 text-muted">
        {listing.title}, {formatUsd(listing.price_usd)} each. Published when {mine ? "you" : "she"} said yes: AI
        shopping agents find it through search, the catalog and the MCP storefront, and {whose} seller agent quotes
        within {whose} limits.
      </p>
      <Link
        href={listing.stall_path}
        className="mt-3 inline-block font-semibold text-accent underline underline-offset-4"
      >
        {mine ? "Open your stall" : "Open her stall"}
      </Link>
    </section>
  );
}
