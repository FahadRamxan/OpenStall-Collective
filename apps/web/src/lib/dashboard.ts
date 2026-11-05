import { apiGet, apiPost } from "@/lib/api";
import type { DataSource } from "@/lib/catalog";
import { TOKEN_HEADER } from "@/lib/demo";
import type { OrderStatus, PartStatus } from "@/lib/orders";

/** One order, as the dashboard lists it. Money is exact, as strings such as "815.00". */
export type DashboardOrder = {
  id: string;
  status: OrderStatus;
  created_at: string;
  approved_at: string | null;
  total_usd: string;
  /** Captured for makers who proved they shipped. */
  paid_usd: string;
  /** Given back to the buyer, never charged. */
  released_usd: string;
  units: number;
  makers: number;
  /** The order a top-up repairs. */
  top_up_of: string | null;
  requested_by_agent: boolean;
};

/** One maker's share of an order: her payout, and her parcel's tracking. */
export type DashboardShare = {
  part_id: string;
  order_id: string;
  reference_id: string;
  seller_id: string;
  maker: string;
  quantity: number;
  amount_usd: string;
  status: PartStatus;
  /** Her payout rail, in words. */
  payout: string;
  paid: boolean;
  carrier: string | null;
  tracking_number: string | null;
  tracking_on_paypal: boolean;
  ship_by: string | null;
  delivered_at: string | null;
  on_time: boolean | null;
  dropped_out: boolean;
};

export type DashboardPassport = {
  seller_id: string;
  name: string;
  orders_delivered: number;
  on_time_rate: number;
  dispute_rate: number;
  photo_originality: number;
  score: number;
  live_deliveries: number;
  data_source: DataSource;
  issued_at: string;
  /** Whether OpenStall's key signed exactly this card; null without a key to check with. */
  signature_valid: boolean | null;
};

/** The maker a Radar group's tip goes to: her listing shares its describing words. */
export type RadarMaker = { seller_id: string; name: string; product_title: string; shared: string[] };

/** One group of searches that found nothing this week (Demand Radar, spec 3.8). */
export type RadarGroup = {
  key: string;
  /** The search as agents typed it most often. */
  label: string;
  searches: number;
  /** How many of them are seeded demo searches. */
  seeded: number;
  queries: string[];
  last_searched_at: string;
  maker: RadarMaker | null;
  /** The dashboard's words, such as "23 agents searched for ceramic mugs this week. Nobody sells them." */
  tip: string;
  /** When its maker was sent the tip this week. */
  tipped_at: string | null;
};

export type Dashboard = {
  /** Test mode: PayPal and the payouts are simulated. */
  simulated: boolean;
  orders: DashboardOrder[];
  shares: DashboardShare[];
  passports: DashboardPassport[];
  radar: RadarGroup[];
};

export function getDashboard(init: RequestInit = {}): Promise<Dashboard> {
  return apiGet<Dashboard>("/api/dashboard", init);
}

/** Sends a Radar group's tip to its maker, in her language. In sandbox mode the API asks for the demo token. */
export function sendRadarTip(key: string, token: string | null = null): Promise<RadarGroup> {
  const init: RequestInit = token ? { headers: { [TOKEN_HEADER]: token } } : {};
  return apiPost<RadarGroup>(`/api/radar/${encodeURIComponent(key)}/tip`, {}, init);
}
