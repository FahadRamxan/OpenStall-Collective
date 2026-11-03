import { ApiError, apiGet } from "@/lib/api";
import { formatUsd } from "@/lib/catalog";
import type { FeedEvent } from "@/lib/events";

/** One maker's share of the order. */
export type PlanLine = {
  seller_id: string;
  seller_name: string;
  offer_id: string | null;
  quantity: number;
  /** USD in whole cents, as strings such as "29.00". */
  unit_price: string;
  line_total: string;
  /** YYYY-MM-DD. */
  delivery_date: string;
};

/** How a quote's order is split across makers, cheapest first, as GET /api/quotes/{id}/plan gives it. */
export type Plan = {
  request_id: string;
  requested_quantity: number;
  total_quantity: number;
  total_cost: string;
  complete: boolean;
  /** Units no valid offer can supply; 0 for a complete plan. */
  shortfall: number;
  /** Why the plan is short, in words; null for a complete plan. */
  reason: string | null;
  lines: PlanLine[];
  /** The plan in 2 or 3 plain sentences; every number in it is in the plan or the request. */
  explanation: string | null;
  /** "model": the model's words, checked; "template": written from the plan. */
  explanation_source: "model" | "template" | null;
  /** Who wrote the explanation, in words for people. */
  explanation_by: string | null;
};

/** The quote's plan, or null while it has none (the quote is still running). */
export async function getPlan(requestId: string, init: RequestInit = {}): Promise<Plan | null> {
  try {
    return await apiGet<Plan>(`/api/quotes/${encodeURIComponent(requestId)}/plan`, init);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** Events after which the latest plan may read differently: a new quote, or a plan stored. */
export function changesPlan(event: FeedEvent): boolean {
  return event.type === "allocation.planned" || event.type === "quote.requested";
}

/** The plan in a few words: "All 40 from 4 makers" or "Only 14 of 40 possible". */
export function planHeadline(plan: Plan): string {
  if (plan.complete) {
    const makers = plan.lines.length === 1 ? "1 maker" : `${plan.lines.length} makers`;
    return `All ${plan.requested_quantity} from ${makers}, ${formatUsd(plan.total_cost)}`;
  }
  return `Only ${plan.total_quantity} of ${plan.requested_quantity} possible`;
}

/** "28%" of the requested quantity, for the share bar. */
export function shareWords(units: number, of: number): string {
  return `${Math.round((units / of) * 100)}%`;
}
