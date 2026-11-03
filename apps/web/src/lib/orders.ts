import { apiGet, apiPost } from "@/lib/api";

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
  /** A verified PayPal webhook confirmed this share's status. */
  confirmed_by_paypal: boolean;
  /** PayPal reported a problem with this share, such as a denied payment. */
  attention: string | null;
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
  /** When PayPal reserved the order: null until then. */
  approved_at: string | null;
  paypal_order_id: string | null;
  parent_order_id: string | null;
  request: BuyerRequest | null;
  parts: OrderPart[];
};

export function getOrder(id: string, init: RequestInit = {}): Promise<Order> {
  return apiGet<Order>(`/api/orders/${encodeURIComponent(id)}`, init);
}

/** Where the human approves the order: PayPal, or the simulated PayPal page in fake mode. */
export type Checkout = { paypal_order_id: string; approval_url: string };

/** Creates the PayPal order for the whole total. Pressing Approve twice gives back the same PayPal order. */
export function startCheckout(id: string): Promise<Checkout> {
  return apiPost<Checkout>(`/api/orders/${encodeURIComponent(id)}/checkout`, {});
}

/** Reserves the approved order at PayPal, once. Calling it again changes nothing and returns the order. */
export function reserveOrder(id: string, init: RequestInit = {}): Promise<Order> {
  return apiPost<Order>(`/api/orders/${encodeURIComponent(id)}/reserve`, {}, init);
}

/** Only a draft, or an order already waiting at PayPal, can be sent to PayPal. */
export function canCheckout(status: OrderStatus): boolean {
  return status === "draft" || status === "awaiting_approval";
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

/** Where each maker's share stands in pay-on-proof, in words for the buyer. */
export const PART_STATUS_LABELS: Record<PartStatus, string> = {
  pending: "Waiting for your approval",
  authorized: "Reserved, paid when she ships",
  captured: "Paid on proof of shipping",
  delivered: "Delivered",
  released: "Released back to you",
};
