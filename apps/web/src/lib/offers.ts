import { apiGet } from "@/lib/api";
import { formatUsd } from "@/lib/catalog";
import type { FeedEvent } from "@/lib/events";

/** One proposal a seller agent made and what the code check said, as GET /api/offers and the offer events give it. */
export type AgentOffer = {
  id: string;
  request_id: string;
  seller_id: string;
  seller_name: string;
  product_id: string | null;
  round: number;
  /** 1 to 3 within the round: a refused proposal is retried with the reason. */
  attempt: number;
  /** USD in whole cents, as a string such as "29.00". */
  unit_price: string;
  quantity: number;
  /** YYYY-MM-DD. */
  delivery_date: string;
  message: string | null;
  is_valid: boolean;
  rejection_reason: string | null;
  /** "valid", or why the code refused it, in words. */
  why: string;
  created_at: string;
};

/** The most recent proposals, newest first. */
export function getRecentOffers(limit = 50, init: RequestInit = {}): Promise<AgentOffer[]> {
  return apiGet<AgentOffer[]>(`/api/offers?limit=${limit}`, init);
}

/** The offer an offer.accepted or offer.rejected event carries, or null for any other event. */
export function offerFromEvent(event: FeedEvent): AgentOffer | null {
  if (event.type !== "offer.accepted" && event.type !== "offer.rejected") return null;
  const row = event.payload as Partial<AgentOffer>;
  // A refused try with no usable price has no offer row: the live feed shows it, the table does not.
  if (!event.entity_id || typeof row.id !== "string" || typeof row.unit_price !== "string") return null;
  if (typeof row.request_id !== "string" || typeof row.seller_name !== "string") return null;
  return row as AgentOffer;
}

/** "Round 1", or "Round 1, try 2" for a retry within the round. */
export function roundWords(offer: AgentOffer): string {
  return offer.attempt > 1 ? `Round ${offer.round}, try ${offer.attempt}` : `Round ${offer.round}`;
}

/** What a screen reader says when an offer arrives: "Grace offered $32.00 each: refused, over the buyer's maximum." */
export function arrivalWords(offer: AgentOffer): string {
  const verdict = offer.is_valid ? "valid" : `refused, ${offer.why}`;
  return `${offer.seller_name} offered ${formatUsd(offer.unit_price)} each: ${verdict}.`;
}
