import { apiGet } from "@/lib/api";
import { formatUsd } from "@/lib/catalog";
import type { FeedEvent } from "@/lib/events";
import { formatDay } from "@/lib/orders";

/** The most rounds a quote runs (spec 3.3). */
export const MAX_ROUNDS = 3;

/** A buyer agent's quote request and how far its negotiation has got, as GET /api/quotes gives it. */
export type Quote = {
  id: string;
  /** What the buyer asked for, in their words: one entry per item. */
  queries: string[];
  quantity: number;
  /** USD in whole cents, as a string such as "30.00". */
  max_unit_price: string;
  /** YYYY-MM-DD. */
  deadline: string;
  ship_to: string;
  created_at: string;
  /** Rounds run so far: 0 until the first round ends. */
  rounds: number;
  /** When the last round ended; null while the agents are still being asked. */
  completed_at: string | null;
  /** Makers whose agents were asked. */
  asked: number;
  /** Makers with a valid offer. */
  valid_offers: number;
  /** Units the valid offers add up to. */
  total_capacity: number;
};

/** The latest quote request, or null when no buyer agent has asked for one yet. */
export async function getLatestQuote(init: RequestInit = {}): Promise<Quote | null> {
  const [latest] = await apiGet<Quote[]>("/api/quotes?limit=1", init);
  return latest ?? null;
}

/** Events after which the latest quote reads differently: a new request, a finished round, a finished quote. */
export function changesQuote(event: FeedEvent): boolean {
  return event.type.startsWith("quote.");
}

/** The request's terms in words: ["40 units", "At most $30.00 each", "By December 10, 2026", "To Chicago"]. */
export function termWords(quote: Quote): string[] {
  return [
    quote.quantity === 1 ? "1 unit" : `${quote.quantity.toLocaleString("en-US")} units`,
    `At most ${formatUsd(quote.max_unit_price)} each`,
    `By ${formatDay(quote.deadline)}`,
    `To ${quote.ship_to}`,
  ];
}

/** Where the negotiation stands, in one sentence. */
export function progressWords(quote: Quote): string {
  const makers = quote.asked === 1 ? "1 maker" : `${quote.asked} makers`;
  if (!quote.completed_at) {
    return quote.rounds === 0
      ? `Asking ${makers}' agents for offers: round 1 of ${MAX_ROUNDS}.`
      : `Round ${quote.rounds + 1} of ${MAX_ROUNDS}: asking again those without a valid offer.`;
  }
  const rounds = quote.rounds === 1 ? "1 round" : `${quote.rounds} rounds`;
  if (quote.asked === 0) return "No maker's listing matches this request, so no agent was asked.";
  const offers = quote.valid_offers === 1 ? "1 valid offer" : `${quote.valid_offers} valid offers`;
  const short = quote.total_capacity < quote.quantity ? `, ${quote.quantity - quote.total_capacity} short` : "";
  return `Done after ${rounds}: ${offers} from ${makers}, for ${quote.total_capacity} units against ${quote.quantity} asked for${short}.`;
}
