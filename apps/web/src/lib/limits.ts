import { apiGet } from "@/lib/api";
import { formatUsd } from "@/lib/catalog";
import type { FeedEvent } from "@/lib/events";

/** One live listing's maker, and what the offer rules let her agent offer by the deadline (GET /api/demo/limits). */
export type MakerLimits = {
  seller_id: string;
  seller_name: string;
  city: string | null;
  product_id: string;
  product_title: string;
  /** USD in whole cents, as a string such as "18.00". */
  list_price_usd: string;
  floor_price_usd: string;
  /** "15" means 15% off her list price at most. */
  max_discount_pct: string;
  /** The lowest unit price her agent may offer: her floor, or her list price less her maximum discount. */
  lowest_price_usd: string;
  capacity_per_week: number;
  ship_days: number;
  min_lead_days: number;
  /** Units she has promised to reserved orders and not shipped yet. */
  committed_units: number;
  /** Units she can still make and ship by the deadline, after her committed units. */
  capacity_by_deadline: number;
  data_source: "seeded_demo" | "live";
};

/** Every live maker's limits by one deadline. */
export type Limits = {
  /** Today in UTC, YYYY-MM-DD: capacity is counted from it. */
  today: string;
  deadline: string;
  makers: MakerLimits[];
  /** Live makers whose limits cannot be read, each said in words. */
  unreadable: string[];
};

/** Every live maker's limits, by 30 days from today (the story's deadline). */
export function getLimits(init: RequestInit = {}): Promise<Limits> {
  return apiGet<Limits>("/api/demo/limits", init);
}

/**
 * Events after which a maker's limits may have changed: a listing goes live, or a share is reserved, paid or released
 * (reserved shares are her committed units).
 */
const CHANGES_LIMITS = new Set([
  "listing.published",
  "part.reserved",
  "order.authorized",
  "part.captured",
  "part.released",
  "part.dropped",
  "order.replanned",
]);

export function changesLimits(event: FeedEvent): boolean {
  return CHANGES_LIMITS.has(event.type);
}

/** Where her lowest price comes from: ["List $18.00", "floor $15.00", "up to 15% off"]. */
export function priceDetails(maker: MakerLimits): string[] {
  return [
    `List ${formatUsd(maker.list_price_usd)}`,
    `floor ${formatUsd(maker.floor_price_usd)}`,
    `up to ${Number(maker.max_discount_pct)}% off`,
  ];
}

/** Where her capacity comes from: ["4 a week", "ships in 9 days"], and what is already promised when there is some. */
export function capacityDetails(maker: MakerLimits): string[] {
  const details = [`${maker.capacity_per_week} a week`, `ships in ${days(maker.ship_days)}`];
  if (maker.committed_units > 0) details.push(`${maker.committed_units} already promised`);
  return details;
}

function days(count: number): string {
  return count === 1 ? "1 day" : `${count} days`;
}
