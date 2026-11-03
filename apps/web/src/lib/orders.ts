import { apiGet } from "@/lib/api";

export type OrderStatus =
  | "draft"
  | "awaiting_approval"
  | "authorized"
  | "partly_shipped"
  | "shipped"
  | "completed"
  | "cancelled";

export type PartStatus = "pending" | "authorized" | "captured" | "delivered" | "released";

/** One maker's share of an order. Money is exact, as strings such as "216.00". */
export type OrderPart = {
  id: string;
  reference_id: string;
  seller: { id: string; name: string; city: string | null; country: string | null };
  product_title: string | null;
  photo: string | null;
  quantity: number;
  unit_price_usd: string;
  amount_usd: string;
  delivery_date: string | null;
  status: PartStatus;
  trust_score: string | null;
  trust_data_source: "seeded_demo" | "live" | null;
};

export type BuyerRequest = {
  summary: string;
  quantity: number;
  max_unit_price: string;
  deadline: string;
  ship_to: string;
};

export type Order = {
  id: string;
  status: OrderStatus;
  total_usd: string;
  units: number;
  created_at: string;
  parent_order_id: string | null;
  request: BuyerRequest | null;
  parts: OrderPart[];
};

export function getOrder(id: string, init: RequestInit = {}): Promise<Order> {
  return apiGet<Order>(`/api/orders/${encodeURIComponent(id)}`, init);
}

const DAY = new Intl.DateTimeFormat("en-US", { month: "long", day: "numeric", year: "numeric", timeZone: "UTC" });

/** "December 10, 2026" from "2026-12-10", the same in every time zone. */
export function formatDay(isoDate: string): string {
  const day = new Date(`${isoDate}T00:00:00Z`);
  return Number.isNaN(day.getTime()) ? isoDate : DAY.format(day);
}

export const ORDER_STATUS_LABELS: Record<OrderStatus, string> = {
  draft: "Waiting for your approval",
  awaiting_approval: "At PayPal",
  authorized: "Reserved",
  partly_shipped: "Partly shipped",
  shipped: "Shipped",
  completed: "Completed",
  cancelled: "Cancelled",
};
