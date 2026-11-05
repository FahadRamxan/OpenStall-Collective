import { apiGet } from "@/lib/api";

/** The home page's numbers (GET /api/overview), worked out when asked. Money is exact, as a string such as "176.00". */
export type Overview = {
  /** Makers with a live listing. */
  makers: number;
  listings: number;
  /** Orders a person approved at PayPal. */
  orders_approved: number;
  /** Paid to makers on proof of shipping. */
  paid_usd: string;
  makers_paid: number;
  /** Parcels a buyer confirmed she received. */
  deliveries: number;
  /** Agents' searches in the last 7 days. */
  agent_searches: number;
  /** Test mode: PayPal is simulated. */
  simulated: boolean;
};

export function getOverview(init: RequestInit = {}): Promise<Overview> {
  return apiGet<Overview>("/api/overview", init);
}

/** Money as a stat tile shows it: "$176", "$206.50", "$12.9K". */
export function tileUsd(value: string): string {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return value;
  if (amount >= 10_000) {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(amount);
  }
  const cents = Math.round(amount * 100) % 100 !== 0;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: cents ? 2 : 0,
    maximumFractionDigits: cents ? 2 : 0,
  }).format(amount);
}
