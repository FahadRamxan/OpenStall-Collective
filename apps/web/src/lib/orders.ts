import { apiGet, apiPost } from "@/lib/api";
import { formatUsd } from "@/lib/catalog";
import type { FeedEvent } from "@/lib/events";

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
  /** When her share must reach the buyer. */
  delivery_date: string | null;
  /** When it must leave her: the delivery date less her listing's ship days. */
  ship_by?: string | null;
  status: PartStatus;
  /** Whether she was told about her share once PayPal held the order; null until then. */
  notice?: PartNotice | null;
  /** Her courier, once she confirmed her tracking. */
  carrier?: string | null;
  /** Her tracking number, set only once she confirmed it: she is paid on it. */
  tracking_number?: string | null;
  /** Her courier receipt photo and what was read from it, from the moment she sends it. */
  proof?: PartProof | null;
  /** A verified PayPal webhook confirmed this share's status. */
  confirmed_by_paypal: boolean;
  /** PayPal reported a problem with this share, such as a denied payment. */
  attention: string | null;
  /**
   * Who confirms this share: the real PayPal sandbox's verified webhooks, or fake mode's simulated PayPal. A simulated
   * confirmation is never shown as "Confirmed by PayPal".
   */
  confirmation_source: ConfirmationSource;
  /** Released while the order's one PayPal hold still serves other shares: never captured, nothing to confirm. */
  nothing_to_confirm: boolean;
  /** How she is paid once her share is captured. */
  payout_rail: PayoutRail;
  /** Her rail in words, for example "Paid to Venmo (simulated)" or "Payout rail not connected yet (Pakistan)". */
  payout_label: string;
  /** Her payout goes through (simulated) PayPal Payouts, so PayPal's webhook will confirm it. */
  payout_via_paypal: boolean;
  /** PayPal said her payout succeeded. */
  payout_confirmed: boolean;
  trust_score: string | null;
  trust_data_source: "seeded_demo" | "live" | null;
};

/** How a maker is paid once her share is captured (spec 3.5a). "unavailable": no rail can reach her yet. */
export type PayoutRail = "paypal" | "venmo" | "hyperwallet" | "unavailable";

/**
 * The message telling a maker about her share: sent (in her language, on WhatsApp or in the web chat), sending (on its
 * way to WhatsApp), or failed (WhatsApp refused it; OpenStall tries again when the order is reserved again).
 */
export type PartNotice = {
  state: "sent" | "sending" | "failed";
  channel: "whatsapp" | "web" | null;
  /** The language she was told in, such as "ur". */
  language: string | null;
  at: string;
  reason?: string | null;
};

/**
 * Her proof of shipping: the courier receipt photo she sent, and the courier and tracking number read from it (or
 * typed by her), waiting for her to confirm, waiting for her to type the number, or confirmed.
 */
export type PartProof = {
  state: "awaiting_confirmation" | "awaiting_number" | "confirmed";
  /** Her receipt photo, a path on the API. */
  photo_url: string | null;
  carrier: string | null;
  tracking_number: string | null;
  source: "photo" | "typed" | null;
  /** Who read the photo, in words for people. */
  read_by: string | null;
};

const NOTICE_CHANNELS = { whatsapp: "on WhatsApp", web: "in the web chat" } as const;

/** Where she was told, in words: "on WhatsApp" or "in the web chat". */
export function noticeChannel(notice: PartNotice): string {
  return notice.channel ? NOTICE_CHANNELS[notice.channel] : "on WhatsApp";
}

/**
 * Shares whose maker is still to be told: reserved, and with no notice yet or one on its way. Only once the API says
 * (an order from an API without notices waits for nothing).
 */
export function awaitingNotices(order: Order): boolean {
  return order.parts.some(
    (part) =>
      part.status === "authorized" &&
      part.notice !== undefined &&
      (part.notice === null || part.notice.state === "sending"),
  );
}

export type ConfirmationSource = "paypal_sandbox" | "simulated";

export type BuyerRequest = {
  summary: string;
  quantity: number;
  max_unit_price: string;
  deadline: string;
  ship_to: string;
  /** The plan in words, from the request's plan; null when the order has none. */
  explanation?: string | null;
  /** Who wrote the explanation, in words for people. */
  explanation_by?: string | null;
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
  /** Drafted by a buyer agent through MCP (create_collective_order). */
  requested_by_agent?: boolean;
  /** The approval link a buyer agent was given to send its human (MCP checkout), once it was. */
  approval_link?: { url: string; issued_at: string } | null;
  parts: OrderPart[];
};

/** The latest order, or null when there is none yet. */
export async function getLatestOrder(init: RequestInit = {}): Promise<Order | null> {
  const [latest] = await apiGet<Order[]>("/api/orders?limit=1", init);
  return latest ?? null;
}

/**
 * Events after which the latest order may read differently: an order or one of its shares changed, or a maker was
 * told about her share (or could not be).
 */
export function changesOrders(event: FeedEvent): boolean {
  return (
    event.type.startsWith("order.") || event.type.startsWith("part.") || event.type.startsWith("message.order_notice")
  );
}

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

/**
 * Fake mode only: simulated proof of shipping for one share, which pays her share as her receipt photo will.
 * Returns the order with the share paid. The API refuses it (404) outside fake mode.
 */
export function simulateProof(partId: string): Promise<Order> {
  return apiPost<Order>(`/api/dev/parts/${encodeURIComponent(partId)}/proof`, {});
}

/** Whether the order's PayPal is the simulated one of fake mode. */
export function isSimulated(order: Order): boolean {
  return order.parts.some((part) => part.confirmation_source === "simulated");
}

/** "Confirmed by PayPal" only for the real PayPal's verified webhooks; fake mode says it is simulated. */
export function confirmedWords(simulated: boolean): string {
  return simulated ? "Confirmed by simulated PayPal" : "Confirmed by PayPal";
}

/** The receipt's one sentence about the money: one authorization, captured share by share. */
export function authorizationSentence(totalUsd: string): string {
  return `One PayPal authorization for ${formatUsd(totalUsd)}. Each maker's share is captured when she ships.`;
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
